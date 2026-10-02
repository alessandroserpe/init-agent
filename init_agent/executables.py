"""Resolve local tools from known installations, never repository PATH entries."""
from __future__ import annotations
import os
import sys
import sysconfig
from pathlib import Path


def resolve_executable(name: str, explicit: str | None = None, root: Path | None = None,
                        *, required: bool = False, verify_explicit: bool = False) -> str | None:
    """Use installation directories, never ambient PATH or the repository.

    An explicit absolute path is the caller's selection of a trusted binary.
    Automatic discovery additionally checks ownership and writable permissions.
    """
    forbidden = [root.resolve()] if root is not None else []
    cwd = Path.cwd().resolve()
    forbidden.extend(parent for parent in (cwd, *cwd.parents)
                     if (parent / ".git").exists() or (parent / "pyproject.toml").exists())
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"{name} requires an explicit absolute executable path")
        candidates = [candidate]
    else:
        candidates = [directory / name for directory in dict.fromkeys([
            Path(sys.executable).parent, Path(sysconfig.get_path("scripts")),
            Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"), Path("/usr/bin"),
        ])]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            if any(resolved.is_relative_to(repo) or candidate.is_relative_to(repo) for repo in forbidden):
                if explicit:
                    raise ValueError(f"Refusing repository executable: {candidate}")
                continue
            if candidate.parent.resolve() == cwd:
                continue
            if not resolved.is_file() or not os.access(resolved, os.X_OK):
                continue
            if (not explicit or verify_explicit) and os.name == "posix":
                chain = [candidate, *candidate.parents, resolved, *resolved.parents]
                if any(path.stat().st_uid not in {0, os.getuid()} or path.stat().st_mode & 0o022 for path in chain):
                    continue
            return str(resolved)
        except (OSError, RuntimeError):
            continue
    if required or explicit:
        raise ValueError(f"No trusted {name} executable found; install it outside the repository or supply an absolute trusted path")
    return None
