"""Shared utilities for init-agent."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".agent",
    ".agents",
    ".codex",
    ".cursor",
    ".vscode",
    ".idea",
    ".history",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".next",
    "storage",
    "cache",
    "logs",
    "tmp",
    "temp",
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
    ".ico",
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
    return root / ".agent"


def db_path(root: Path) -> Path:
    return agent_dir(root) / "graph.sqlite"


def config_path(root: Path) -> Path:
    return agent_dir(root) / "config.json"


def ensure_agent_dir(root: Path) -> None:
    agent_dir(root).mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text_safely(path: Path, max_bytes: int = 2_000_000) -> str | None:
    """Read text for mapping only, skipping likely binary or very large files."""

    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
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
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def load_ignore_rules(root: Path) -> dict[str, set[str]]:
    rules = {
        "exclude_dirs": set(DEFAULT_EXCLUDED_DIRS),
        "exclude_files": set(DEFAULT_EXCLUDED_FILES),
        "exclude_extensions": set(DEFAULT_EXCLUDED_EXTENSIONS),
    }
    path = config_path(root)
    if not path.exists():
        return rules
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return rules
    for key in rules:
        values = data.get(key, [])
        if isinstance(values, list):
            rules[key].update(str(value) for value in values if str(value))
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
    if path.name in ignore["exclude_files"]:
        return False
    if path.suffix.lower() in ignore["exclude_extensions"]:
        return False
    return True


def iter_indexable_files(root: Path, rules: dict[str, set[str]] | None = None) -> list[Path]:
    ignore = rules or load_ignore_rules(root)
    files = []
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in ignore["exclude_dirs"] and is_indexable_path(current / dirname, root, ignore)
        ]
        for filename in filenames:
            path = current / filename
            if path.is_file() and is_indexable_path(path, root, ignore):
                files.append(path)
    return sorted(files)


def is_hidden_or_excluded_dir(path: Path, root: Path, excluded: set[str]) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return True
    return any(part in excluded for part in rel_parts)


def format_count(label: str, count: int) -> str:
    return f"{label}: {count}"


def mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def env_with_clean_locale() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    return env
