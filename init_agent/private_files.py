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
    if not directory and stat.S_ISREG(info.st_mode) and info.st_nlink == 0:
        raise FileNotFoundError(f'Metadata was removed after opening: {path!r}')
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
    if path.parent.name == '.agent':
        with MetadataDirectory(path.parent.parent) as directory:
            with directory.open(path.name, mode) as handle:
                yield handle
        return
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


class MetadataDirectory:
    """Hold the owner-only metadata directory for the full operation lifetime."""
    def __init__(self, root: Path, *, create: bool = False):
        self.root = root.resolve()
        self.path = self.root / '.agent'
        self.fd = -1
        if os.open not in os.supports_dir_fd or not hasattr(os, 'O_NOFOLLOW'):
            raise OSError('secure metadata access requires directory descriptors and O_NOFOLLOW')
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if create:
                try:
                    os.mkdir('.agent', 0o700, dir_fd=parent)
                except FileExistsError:
                    pass
            try:
                self.fd = os.open('.agent', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except OSError as exc:
                if self.path.is_symlink():
                    raise OSError('Refusing symlinked .agent directory') from exc
                raise
            _check_descriptor(self.fd, self.path, directory=True)
            self.validate_children()
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent)

    def validate_children(self):
        # The direct-child namespace is files only: database, fixed sidecars,
        # configuration, exports, backups and logs. No subdirectories/devices.
        with os.scandir(self.fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 256:
                    raise OSError('too many direct .agent children (maximum 256)')
                try:
                    with self.open(entry.name, 'rb'):
                        pass
                except FileNotFoundError:
                    # SQLite deletes these transient files during normal commits.
                    # No bytes or writes are performed through the removed inode.
                    if entry.name not in {'graph.sqlite-journal', 'graph.sqlite-wal', 'graph.sqlite-shm'}:
                        raise

    @contextmanager
    def open(self, name: str, mode: str = 'rb'):
        if not name or Path(name).name != name or name in {'.', '..'}:
            raise OSError('invalid metadata child name')
        flags = os.O_RDONLY if mode.startswith('r') else os.O_WRONLY | os.O_CREAT
        flags |= os.O_NOFOLLOW | os.O_NONBLOCK
        if mode.startswith('a'):
            flags |= os.O_APPEND
        try:
            fd = os.open(name, flags, 0o600, dir_fd=self.fd)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise OSError(f'Refusing unsafe metadata child {name!r}: {exc.strerror}') from exc
        try:
            _check_descriptor(fd, self.path / name)
            if mode.startswith('w'):
                os.ftruncate(fd, 0)
            handle = os.fdopen(fd, mode, **({} if 'b' in mode else {'encoding': 'utf-8'}))
        except BaseException:
            os.close(fd)
            raise
        with handle:
            yield handle

    def verify_identity(self):
        opened = os.fstat(self.fd)
        current = os.stat(self.path, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino) or not stat.S_ISDIR(current.st_mode):
            raise OSError('.agent directory changed during metadata access')

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def require_private_sqlite_path(directory: Path) -> None:
    """SQLite uses pathnames: exclude cross-user rename rights on every ancestor.

    A root-owned sticky temp directory is permitted; the next component must
    still be owned by this user/root. This does not sandbox same-UID processes.
    """
    if os.name != 'posix':
        raise OSError('secure SQLite metadata access currently requires POSIX ownership checks')
    path = directory.resolve()
    for component in [Path(path.anchor), *reversed(path.parents[:-1]), path]:
        fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX) and component != path
            if info.st_uid not in {0, os.getuid()} or (info.st_mode & 0o022 and not sticky_root):
                raise PermissionError(f'SQLite metadata requires a path not writable by other users: {component!r}')
            if _macos_acl_allows_write(fd):
                raise PermissionError(f'SQLite metadata path has a write-granting ACL: {component!r}')
        finally:
            os.close(fd)


def _macos_acl_allows_write(fd: int) -> bool:
    if sys.platform != 'darwin':
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    pointer = ctypes.c_void_p
    libc.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    libc.acl_get_fd_np.restype = pointer
    libc.acl_get_entry.argtypes = [pointer, ctypes.c_int, ctypes.POINTER(pointer)]
    libc.acl_get_tag_type.argtypes = [pointer, ctypes.POINTER(ctypes.c_int)]
    libc.acl_get_permset.argtypes = [pointer, ctypes.POINTER(pointer)]
    libc.acl_get_perm_np.argtypes = [pointer, ctypes.c_int]
    libc.acl_free.argtypes = [pointer]
    acl = libc.acl_get_fd_np(fd, 0x100)
    if not acl:
        return False
    try:
        entry, perms, tag = pointer(), pointer(), ctypes.c_int()
        selector = 0  # ACL_FIRST_ENTRY; ACL_NEXT_ENTRY is -1 on Darwin.
        while libc.acl_get_entry(acl, selector, ctypes.byref(entry)) == 0 and entry.value:
            selector = -1
            if libc.acl_get_tag_type(entry, ctypes.byref(tag)) != 0:
                return True
            if tag.value == 1:  # ACL_EXTENDED_ALLOW
                if libc.acl_get_permset(entry, ctypes.byref(perms)) != 0:
                    return True
                if any(libc.acl_get_perm_np(perms, 1 << bit) != 0 for bit in (2, 4, 5, 6, 8, 10, 12, 13)):
                    return True
        return False
    finally:
        libc.acl_free(acl)
