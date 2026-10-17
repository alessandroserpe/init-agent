"""Optional, isolated TypeScript compiler analyzer.

The worker parses source only; it never loads or executes repository modules.
Install its pinned compiler separately with ``npm ci`` in typescript_worker/.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .bounded_process import run_bounded

WORKER_DIR = Path(__file__).resolve().parent / "typescript_worker"
WORKER = WORKER_DIR / "worker.js"
COMPILER = WORKER_DIR / "node_modules" / "typescript" / "lib" / "typescript.js"
TIMEOUT_SECONDS = 20
OUTPUT_BYTES = 2 * 1024 * 1024
INPUT_BYTES = 64 * 1024
ADAPTER_VERSION = "1"
PINNED_TYPESCRIPT_VERSION = "5.8.3"


def _unavailable(gap: str) -> dict[str, Any]:
    return {"analyzer": "typescript-compiler", "version": None, "structural": False,
            "symbols": [], "edges": [], "gaps": [gap]}


def compiler_fingerprint() -> str:
    """Stable analyzer identity for invalidating structural results."""
    node = shutil.which("node")
    available = bool(node and COMPILER.is_file())
    return f"typescript-compiler:{ADAPTER_VERSION}:{PINNED_TYPESCRIPT_VERSION}:{int(available)}"


def analyze(root: Path, path: str) -> dict[str, Any]:
    """Analyze one TypeScript file and its statically resolved local imports."""
    root = Path(root).resolve()
    requested = Path(path)
    if requested.is_absolute() or ".." in requested.parts:
        return _unavailable("target must be a root-relative path")
    target = root / requested
    cursor = root
    for part in requested.parts:
        if part in {"", "."}:
            continue
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                return _unavailable("target path contains a symlink")
        except OSError:
            return _unavailable("target path cannot be safely inspected")
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return _unavailable("target is outside analysis root")
    if "node_modules" in target.parts or not target.is_file():
        return _unavailable("target is missing or excluded")
    node = shutil.which("node")
    if not node or not COMPILER.is_file():
        return _unavailable("optional TypeScript compiler unavailable; install pinned worker dependency with npm ci")
    payload = json.dumps({"root": str(root), "path": target.relative_to(root).as_posix()}, separators=(",", ":")).encode()
    if len(payload) > INPUT_BYTES:
        return _unavailable("analysis request limit exceeded")
    command = [node, "--max-old-space-size=384", str(WORKER)]
    # Repository-controlled Node options and module search paths must not
    # influence the compiler worker.
    env = {"PATH": str(Path(node).resolve().parent), "LANG": "C", "LC_ALL": "C"}
    if "SystemRoot" in os.environ:
        env["SystemRoot"] = os.environ["SystemRoot"]
    try:
        result = run_bounded(command, cwd=WORKER_DIR, input_bytes=payload,
                             timeout=TIMEOUT_SECONDS, max_bytes=OUTPUT_BYTES, check=False, env=env)
    except (subprocess.CalledProcessError, OSError):
        return _unavailable("TypeScript worker exceeded its runtime or output budget")
    if result.returncode != 0:
        return _unavailable("TypeScript worker failed or exceeded its memory budget")
    try:
        value = json.loads(result.stdout)
        if (not isinstance(value, dict) or value.get("analyzer") != "typescript-compiler"
                or not isinstance(value.get("version"), str) or not isinstance(value.get("structural"), bool)
                or not all(isinstance(value.get(key), list) for key in ("symbols", "edges", "gaps"))
                or not isinstance(value.get("dependencies"), dict)
                or not isinstance(value.get("config_fingerprint"), str)):
            raise ValueError("invalid result shape")
        return value
    except (ValueError, TypeError, RecursionError):
        return _unavailable("invalid TypeScript worker result")
