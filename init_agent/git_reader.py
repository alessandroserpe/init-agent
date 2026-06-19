"""Read-only Git metadata collection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .utils import env_with_clean_locale


def has_git(root: Path) -> bool:
    return (root / ".git").exists()


def git_available(root: Path) -> bool:
    if not has_git(root):
        return False
    result = _git(root, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(root: Path) -> str | None:
    result = _git(root, "branch", "--show-current")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    result = _git(root, "rev-parse", "--short", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def status_short(root: Path) -> list[str]:
    result = _git(root, "status", "--short")
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def recent_commits(root: Path, limit: int = 50) -> list[dict[str, object]]:
    result = _git(root, "log", f"--max-count={limit}", "--format=%H%x1f%aI%x1f%an%x1f%s")
    if result.returncode != 0:
        return []

    commits: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        commit_hash, date, author, message = parts
        commits.append(
            {
                "hash": commit_hash,
                "date": date,
                "author": author,
                "message": message,
                "files": commit_files(root, commit_hash),
            }
        )
    return commits


def commit_files(root: Path, commit_hash: str) -> list[str]:
    result = _git(root, "show", "--pretty=format:", "--name-only", commit_hash)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_git(root: Path) -> dict[str, object]:
    if not git_available(root):
        return {"git": False, "branch": None, "status": [], "commits": []}
    return {
        "git": True,
        "branch": current_branch(root),
        "status": status_short(root),
        "commits": recent_commits(root),
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        env=env_with_clean_locale(),
        text=True,
        capture_output=True,
        check=False,
    )
