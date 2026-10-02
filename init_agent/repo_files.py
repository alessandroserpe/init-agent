"""Descriptor-anchored reads: repository descendants must never be symlinks."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import stat

from .repo_budget import checkpoint


@contextmanager
def open_repo_file(root: Path, relative: str | Path):
    path = Path(relative)
    if path.is_absolute() or not path.parts or '..' in path.parts:
        raise OSError('invalid repository-relative file path')
    if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
        raise OSError('secure repository reads require openat and O_NOFOLLOW')
    # The selected root is trusted; every mutable descendant is opened relative
    # to the preceding directory descriptor, with no symlink traversal.
    directory = os.open(root.resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError('repository input is not a regular file')
            handle = os.fdopen(fd, 'rb')
        except BaseException:
            os.close(fd)
            raise
        with handle:
            yield handle
    finally:
        os.close(directory)


def stat_mtime(info: os.stat_result) -> str:
    return datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(timespec='seconds')


@dataclass(frozen=True)
class FileSnapshot:
    info: os.stat_result
    sha256: str
    content: str | None


def repo_snapshot(root: Path, relative: str | Path, max_text: int = 2_000_000) -> FileSnapshot:
    with open_repo_file(root, relative) as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.sha256()
        data = bytearray()
        total = 0
        for chunk in iter(lambda: handle.read(64 * 1024), b''):
            checkpoint('io_bytes', len(chunk))
            total += len(chunk)
            # Also bound standalone callers without a request budget.
            if total > 64 * 1024 * 1024:
                raise OSError('repository file exceeds hash budget')
            digest.update(chunk)
            if total <= max_text:
                data.extend(chunk)
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or total != after.st_size:
            raise OSError('repository file changed during read')
        content = None
        if total <= max_text and b'\x00' not in data[:4096]:
            try:
                content = data.decode('utf-8')
            except UnicodeDecodeError:
                content = data.decode('latin-1')
        return FileSnapshot(after, digest.hexdigest(), content)
