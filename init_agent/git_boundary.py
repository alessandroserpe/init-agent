"""Bind Git reads to administrative data inside the selected repository."""
import os
from pathlib import Path
import stat

from .repo_budget import CURRENT_BUDGET, checkpoint
from .repo_files import open_repo_file


def _small_file(root, relative, limit=65536):
    with open_repo_file(root, relative) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise OSError('Git administrative file exceeds validation limit')
    return data


def validated_git_dir(root: Path) -> Path:
    root = root.resolve()
    budget = CURRENT_BUDGET.get()
    cache = getattr(budget, '_validated_git_dirs', {}) if budget else {}
    if str(root) in cache:
        return cache[str(root)]
    entry = root / '.git'
    info = entry.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise OSError('symlinked .git is not supported')
    if stat.S_ISDIR(info.st_mode):
        admin = entry
    elif stat.S_ISREG(info.st_mode):
        data = _small_file(root, '.git', 4096)
        try:
            line = data.decode('utf-8').strip()
        except UnicodeDecodeError as exc:
            raise OSError('invalid gitdir file') from exc
        if not line.startswith('gitdir: ') or '\n' in line or '\r' in line:
            raise OSError('invalid gitdir file')
        target = Path(line[8:])
        if target.is_absolute() or '..' in target.parts or not target.parts:
            raise OSError('external gitdir is not supported; use a self-contained checkout')
        admin = root / target
        current = root
        for part in target.parts:
            current /= part
            if not stat.S_ISDIR(current.lstat().st_mode):
                raise OSError('gitdir must use real in-repository directories')
    else:
        raise OSError('unexpected .git type')
    # Reject indirection anywhere in refs/objects, including linked worktrees
    # and alternates. A self-contained checkout is the supported boundary.
    pending = [admin]
    count = 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for item in entries:
                count += 1
                checkpoint()
                if count > 20000:
                    raise OSError('Git administrative validation exceeds 20000 entries')
                info = item.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(item.path))
                elif not stat.S_ISREG(info.st_mode):
                    raise OSError('Git administrative tree contains a symlink or special file')
                elif item.name in {'commondir', 'alternates', 'http-alternates'}:
                    if _small_file(root, Path(item.path).relative_to(root)).strip():
                        raise OSError('Git common directories and object alternates are not supported')
    if budget:
        cache[str(root)] = admin
        budget._validated_git_dirs = cache
    return admin
