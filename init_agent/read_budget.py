"""Per-request limits for reading and traversing untrusted repository metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic

from .utils import is_live_repo_file


@dataclass
class ReadBudget:
    max_bytes: int = 8 * 1024 * 1024
    max_file_bytes: int = 256 * 1024
    max_files: int = 256
    max_states: int = 1000
    max_seconds: float = 5.0
    bytes_read: int = 0
    states: int = 0
    truncated: bool = False
    started: float = field(default_factory=monotonic)
    cache: dict[str, str] = field(default_factory=dict)

    def expired(self) -> bool:
        if monotonic() - self.started >= self.max_seconds:
            self.truncated = True
            return True
        return False

    def visit(self) -> bool:
        if self.expired() or self.states >= self.max_states:
            self.truncated = True
            return False
        self.states += 1
        return True

    def text(self, root: Path, path: str) -> str:
        if path in self.cache:
            return self.cache[path]
        if self.expired() or len(self.cache) >= self.max_files or self.bytes_read >= self.max_bytes:
            self.truncated = True
            return ""
        self.cache[path] = ""
        if not is_live_repo_file(root, path):
            return ""
        allowance = min(self.max_file_bytes, self.max_bytes - self.bytes_read)
        try:
            with (root / path).open("rb") as handle:
                data = handle.read(allowance)
                if (root / path).stat().st_size > len(data):
                    self.truncated = True
        except OSError:
            return ""
        self.bytes_read += len(data)
        if b"\x00" in data[:4096]:
            return ""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        self.cache[path] = text
        return text
