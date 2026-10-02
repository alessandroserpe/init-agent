"""Owner-only metadata files without changing the process-wide umask."""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, IO, Any


def _check_descriptor(fd: int, path: Path, *, directory: bool = False) -> None:
    info = os.fstat(fd)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or (not directory and info.st_nlink != 1):
        raise PermissionError(f"Refusing non-regular or hard-linked metadata: {path!r}")
    if os.name == "posix":
        if info.st_uid != os.getuid():
            raise PermissionError(f"Metadata is not owned by the current user: {path!r}")
        os.fchmod(fd, 0o700 if directory else 0o600)
        if _has_macos_acl(fd):
            warnings.warn(f"Metadata {path!r} has an extended ACL; review it for additional access grants.", RuntimeWarning)


def _has_macos_acl(fd: int) -> bool:
    if sys.platform != "darwin":
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    get_acl = libc.acl_get_fd_np
    get_acl.argtypes = [ctypes.c_int, ctypes.c_int]
    get_acl.restype = ctypes.c_void_p
    get_entry = libc.acl_get_entry
    get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    free_acl = libc.acl_free
    free_acl.argtypes = [ctypes.c_void_p]
    acl = get_acl(fd, 0x100)  # ACL_TYPE_EXTENDED on Darwin.
    if not acl:
        return False
    try:
        entry = ctypes.c_void_p()
        return get_entry(acl, 0, ctypes.byref(entry)) == 0 and bool(entry.value)
    finally:
        free_acl(acl)


def harden_private_path(path: Path, *, directory: bool = False) -> None:
    if path.is_symlink():
        raise PermissionError(f"Refusing symlinked metadata: {path!r}")
    if directory and os.name != "posix":
        if not path.is_dir():
            raise PermissionError(f"Metadata directory is not a directory: {path!r}")
        return  # Native ACLs remain the operator's responsibility on Windows.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        _check_descriptor(fd, path, directory=directory)
    finally:
        os.close(fd)


def ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    harden_private_path(path, directory=True)


@contextmanager
def private_open(path: Path, mode: str = "w") -> Iterator[IO[Any]]:
    if path.is_symlink():
        raise PermissionError(f"Refusing symlinked metadata: {path!r}")
    flags = (os.O_RDONLY if mode.startswith("r") else os.O_WRONLY | os.O_CREAT)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if mode.startswith("a"):
        flags |= os.O_APPEND
    fd = os.open(path, flags, 0o600)
    try:
        _check_descriptor(fd, path)
        if mode.startswith("w"):
            os.ftruncate(fd, 0)
        handle = os.fdopen(fd, mode, **({} if "b" in mode else {"encoding": "utf-8"}))
    except BaseException:
        os.close(fd)
        raise
    with handle:
        yield handle


def write_private_text(path: Path, value: str) -> None:
    with private_open(path) as handle:
        handle.write(value)


def copy_private_file(source: Path, target: Path) -> None:
    with private_open(source, "rb") as reader, private_open(target, "wb") as writer:
        shutil.copyfileobj(reader, writer)
