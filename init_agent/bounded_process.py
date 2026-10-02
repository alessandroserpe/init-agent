"""Parent-owned subprocess budgets for local tools and benchmark phases."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

PHASE_SECONDS = 120.0
OUTPUT_BYTES = 1_048_576


def run_bounded(command: list[str], *, cwd: str | Path, env=None, check: bool = True,
                timeout: float = PHASE_SECONDS, max_bytes: int = OUTPUT_BYTES) -> subprocess.CompletedProcess:
    """Capture at most max_bytes across both streams and kill the process tree."""
    if timeout <= 0 or max_bytes < 1:
        raise ValueError("process budgets must be positive")
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, **options)
    chunks: queue.Queue = queue.Queue(maxsize=8)
    stop = threading.Event()

    def read_stream(stream, label):
        try:
            while not stop.is_set():
                block = os.read(stream.fileno(), 4096)
                while not stop.is_set():
                    try:
                        chunks.put((label, block), timeout=0.05)
                        break
                    except queue.Full:
                        continue
                if not block:
                    break
        except OSError:
            pass

    readers = [threading.Thread(target=read_stream, args=(stream, label), daemon=True)
               for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr"))]
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    failure = None
    used = closed = 0
    try:
        for reader in readers:
            reader.start()
        while closed < 2 or proc.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "benchmark phase deadline exceeded"
                break
            try:
                label, block = chunks.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                continue
            if not block:
                closed += 1
                continue
            available = max_bytes - used
            captured[label].extend(block[:available])
            used += min(len(block), available)
            if len(block) > available:
                failure = "benchmark phase output limit exceeded"
                break
    finally:
        stop.set()
        # Also remove descendants after the leader exits: they may hold pipes open.
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif proc.poll() is None:
            try:
                subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                                "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
            finally:
                if proc.poll() is None:
                    proc.kill()
        proc.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=0.2)
        proc.stdout.close()
        proc.stderr.close()
    stdout, stderr = (captured[key].decode("utf-8", errors="replace") for key in ("stdout", "stderr"))
    if failure:
        raise subprocess.CalledProcessError(124, command, output=stdout, stderr=failure)
    result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result
