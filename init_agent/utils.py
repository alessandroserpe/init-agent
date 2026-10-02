"""Shared utilities for init-agent."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import subprocess
import stat
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .repo_budget import CURRENT_BUDGET, WorkBudgetExceeded, bounded_operation, checkpoint
from .bounded_process import run_bounded
from .executables import resolve_executable
from .private_files import MetadataDirectory, private_open, write_private_text


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".agent",
    ".agents",
    ".codex",
    ".cursor",
    ".vscode",
    ".idea",
    ".history",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".turbo",
    ".parcel-cache",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "out",
    "target",
    ".venv",
    "venv",
    "env",
    ".env",
    "__pycache__",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "storage",
    "cache",
    "coverage",
    "htmlcov",
    "logs",
    "tmp",
    "temp",
}

DEFAULT_EXCLUDED_DIR_SUFFIXES = {
    ".egg-info",
    ".dist-info",
}

DEFAULT_EXCLUDED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

DEFAULT_EXCLUDED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".ai",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".sqlite",
    ".db",
}


PROJECT_MARKERS = {
    ".git",
    "pyproject.toml",
    "package.json",
    "composer.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "README.md",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_root(start: Path | None = None) -> Path:
    """Return the current working directory as project root.

    The CLI is intentionally local-first: it indexes the directory where it is
    invoked instead of traversing upward and surprising the caller.
    """

    return (start or Path.cwd()).resolve()


def has_project_marker(root: Path) -> bool:
    return any((root / marker).exists() for marker in PROJECT_MARKERS)


def agent_dir(root: Path) -> Path:
    directory = root / ".agent"
    try:
        with MetadataDirectory(root):
            pass
    except FileNotFoundError:
        if directory.is_symlink():
            raise OSError("Refusing symlinked .agent directory")
    return directory


def db_path(root: Path) -> Path:
    return agent_dir(root) / "graph.sqlite"


def config_path(root: Path) -> Path:
    return agent_dir(root) / "config.json"


def ensure_agent_dir(root: Path) -> None:
    with MetadataDirectory(root, create=True):
        pass


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            checkpoint('io_bytes', len(chunk))
            digest.update(chunk)
    return digest.hexdigest()


def read_text_safely(path: Path, max_bytes: int = 2_000_000) -> str | None:
    """Read text for mapping only, skipping likely binary or very large files."""

    try:
        if path.stat().st_size > max_bytes:
            return None
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
            checkpoint('io_bytes', len(data))
        if len(data) > max_bytes:
            return None
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_private_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def relative_path(path: Path, root: Path) -> str:
    return path.absolute().relative_to(root.absolute()).as_posix()


def normalize_repo_path(path: str | Path | None) -> str:
    """Normalize a project-relative path without stripping leading dotfiles."""

    normalized = Path(path or "").as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return "" if normalized == "." else normalized


def is_live_repo_file(root: Path, path: str | Path | None) -> bool:
    """Return whether a normalized path is a regular file inside the project."""

    try:
        normalized = normalize_repo_path(path)
        relative = Path(normalized)
        if not normalized or relative.is_absolute() or ".." in relative.parts:
            return False
        from .repo_files import open_repo_file
        with open_repo_file(root, relative):
            return True
    except (OSError, ValueError, RuntimeError):
        return False


def shell_quote(value: str) -> str:
    """Quote one POSIX shell argument, including expansion characters."""
    escaped = str(value)
    for char in ('\\', '"', '$', '`'):
        escaped = escaped.replace(char, '\\' + char)
    return '"' + escaped + '"'


def terminal_safe(value: str) -> str:
    """Make terminal controls visible while retaining layout newlines and tabs."""
    return "".join(
        (f"\\x{ord(char):02x}" if ord(char) <= 0xff else f"\\u{ord(char):04x}")
        if unicodedata.category(char) in {"Cc", "Cf"} and char not in "\n\t"
        else char
        for char in value
    )


def safe_print(*values: object, **kwargs: Any) -> None:
    builtins.print(*(terminal_safe(str(value)) for value in values), **kwargs)


MAX_CONFIG_BYTES = 65_536
MAX_CONFIG_DEPTH = 4
MAX_CONFIG_ITEMS = 256
MAX_CONFIG_STRING = 1024


def _bounded_config(path: Path) -> dict[str, Any]:
    with private_open(path, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES:
            raise ValueError("invalid configuration file size/type")
        raw = handle.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("configuration byte limit exceeded")
    text = raw.decode("utf-8")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_CONFIG_DEPTH:
                raise ValueError("configuration nesting limit exceeded")
        elif char in "]}":
            depth -= 1
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("configuration must be an object")
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, (dict, list)):
            if len(value) > MAX_CONFIG_ITEMS:
                raise ValueError("configuration collection limit exceeded")
            pending.extend(value.keys() if isinstance(value, dict) else [])
            pending.extend(value.values() if isinstance(value, dict) else value)
        elif isinstance(value, str) and len(value) > MAX_CONFIG_STRING:
            raise ValueError("configuration string limit exceeded")
    return data


def load_ignore_rules(root: Path) -> dict[str, set[str]]:
    rules = {
        "exclude_dirs": set(DEFAULT_EXCLUDED_DIRS),
        "exclude_files": set(DEFAULT_EXCLUDED_FILES),
        "exclude_extensions": set(DEFAULT_EXCLUDED_EXTENSIONS),
        "include_hidden_dirs": set(),
    }
    try:
        data = _bounded_config(config_path(root))
        for key in rules:
            values = data.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("ignore rules must be lists of strings")
    except (OSError, ValueError, RecursionError):
        return rules
    for key in rules:
        rules[key].update(value for value in data.get(key, []) if value)
    rules["exclude_extensions"] = {
        value if value.startswith(".") else f".{value}"
        for value in rules["exclude_extensions"]
    }
    return rules


def is_indexable_path(path: Path, root: Path, rules: dict[str, set[str]] | None = None) -> bool:
    ignore = rules or load_ignore_rules(root)
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    if any(part in ignore["exclude_dirs"] for part in rel_parts[:-1]):
        return False
    if any(_is_excluded_dir_part(part) for part in rel_parts[:-1]):
        return False
    if any(_is_hidden_dir_part(part, ignore) for part in rel_parts[:-1]):
        return False
    if path.name in ignore["exclude_files"]:
        return False
    if path.suffix.lower() in ignore["exclude_extensions"]:
        return False
    return True


@bounded_operation
def iter_indexable_files(root: Path, rules: dict[str, set[str]] | None = None) -> list[Path]:
    ignore = rules or load_ignore_rules(root)
    git_paths = _git_indexable_paths(root)
    if git_paths is not None:
        files = []
        for rel_path in git_paths:
            checkpoint('entries')
            _check_path_complexity(Path(rel_path))
            path = root / rel_path
            if path.is_file() and is_indexable_path(path, root, ignore):
                files.append(path)
        return sorted(files)
    files = []
    pending = [root]
    while pending:
        checkpoint()
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                checkpoint('entries')
                path = Path(entry.path)
                _check_path_complexity(path.relative_to(root))
                if entry.is_dir(follow_symlinks=False):
                    if (entry.name not in ignore["exclude_dirs"]
                            and not _is_excluded_dir_part(entry.name)
                            and not _is_hidden_dir_part(entry.name, ignore)
                            and is_indexable_path(path, root, ignore)):
                        pending.append(path)
                elif entry.is_file() and is_indexable_path(path, root, ignore):
                    files.append(path)
    return sorted(files)


def _check_path_complexity(path: Path) -> None:
    if len(str(path)) > 4096 or len(path.parts) > 64:
        raise WorkBudgetExceeded("repository path complexity limit exceeded; results are incomplete")


def is_hidden_or_excluded_dir(path: Path, root: Path, excluded: set[str]) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(part in excluded for part in rel_parts)


def _is_excluded_dir_part(part: str) -> bool:
    return any(part.endswith(suffix) for suffix in DEFAULT_EXCLUDED_DIR_SUFFIXES)


def _is_hidden_dir_part(part: str, ignore: dict[str, set[str]]) -> bool:
    if not part.startswith(".") or part in {".", ".."}:
        return False
    return part not in ignore.get("include_hidden_dirs", set())


def _git_indexable_paths(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    try:
        result = run_git_read(root, "ls-files", "-co", "--exclude-standard")
    except (OSError, ValueError):
        return None
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def format_count(label: str, count: int) -> str:
    return f"{label}: {count}"


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def env_with_clean_locale() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    return env


def git_read_command(root: Path | None = None) -> list[str]:
    """Disable executable Git configuration in repository metadata reads."""
    return [resolve_executable("git", root=root, required=True), "--no-pager", "-c", "core.fsmonitor=", "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.untrackedCache=false", "-c", "diff.external=", "-c", "submodule.recurse=false"]


def git_read_environment() -> dict[str, str]:
    env = env_with_clean_locale()
    env["PATH"] = os.pathsep.join(str(path) for path in (Path("/usr/bin"), Path("/bin")) if path.is_dir()) if os.name == "posix" else str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat"})
    return env


@bounded_operation
def run_git_read(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    budget = CURRENT_BUDGET.get()
    budget.check()
    command = [*git_read_command(root), *args]
    remaining = budget.limits['git_bytes'] - budget.used.get('git_bytes', 0)
    if remaining <= 0:
        budget.check('git_bytes', 1)
    import time
    timeout = min(10.0, budget.max_seconds - (time.monotonic() - budget.started))
    budget.check(amount=0)
    try:
        result = run_bounded(command, cwd=root, env=git_read_environment(), check=False,
                             timeout=max(0.001, timeout), max_bytes=min(2 * 1024 * 1024, remaining))
    except subprocess.CalledProcessError as exc:
        budget.reason = 'Git subprocess output/deadline limit'
        raise WorkBudgetExceeded('repository Git work budget exceeded; results are incomplete') from exc
    budget.check('git_bytes', len(result.stdout.encode('utf-8')) + len(result.stderr.encode('utf-8')))
    return result
