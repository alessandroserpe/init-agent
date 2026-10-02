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
    validate_git_config(root, admin)
    if budget:
        cache[str(root)] = admin
        budget._validated_git_dirs = cache
    return admin


# Deliberately small non-executing configuration surface. Unknown syntax/keys
# are refused, rather than trying to enumerate every current/future helper.
_SAFE_CONFIG = {
    'core': {'repositoryformatversion', 'filemode', 'bare', 'logallrefupdates',
             'ignorecase', 'precomposeunicode', 'symlinks', 'autocrlf', 'safecrlf',
             'eol', 'ignorestat', 'trustctime', 'checkstat', 'protectntfs', 'protecthfs'},
    'user': {'name', 'email'},
    'remote': {'url', 'fetch', 'pushurl'},
    'branch': {'remote', 'merge', 'rebase'},
    'init': {'defaultbranch'},
    'extensions': {'objectformat'},
}


def validate_git_config(root: Path, admin: Path) -> None:
    import re
    from .private_files import require_private_sqlite_path, _macos_acl_allows_write
    require_private_sqlite_path(admin)
    relative = admin.relative_to(root) / 'config'
    try:
        with open_repo_file(root, relative) as handle:
            info = os.fstat(handle.fileno())
            if info.st_uid not in {0, os.getuid()} or info.st_mode & 0o022 or _macos_acl_allows_write(handle.fileno()):
                raise OSError('Git config must not be writable by other users')
            raw = handle.read(65537)
    except FileNotFoundError:
        return
    if len(raw) > 65536:
        raise OSError('Git config exceeds validation limit')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise OSError('unsupported Git config encoding') from exc
    if '\\' in text or any(ord(c) < 32 and c not in '\r\n\t' for c in text):
        raise OSError('unsupported Git config escapes/continuations/control characters')
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('['):
            match = re.fullmatch(r'\[([A-Za-z][A-Za-z0-9-]*)(?:\s+"[^"\r\n]*")?\]\s*(?:[#;].*)?', line)
            if not match or match[1].lower() not in _SAFE_CONFIG:
                raise OSError('Git config section is outside the non-executing allowlist')
            section = match[1].lower()
        else:
            match = re.fullmatch(r'([A-Za-z][A-Za-z0-9-]*)\s*(?:=.*)?', line)
            if section is None or not match or match[1].lower() not in _SAFE_CONFIG[section]:
                raise OSError('Git config key is outside the non-executing allowlist')
    # Additional worktree configuration is never part of this policy.
    if (admin / 'config.worktree').exists():
        raise OSError('Git worktree configuration is not supported')
