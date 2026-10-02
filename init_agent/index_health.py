"""Lightweight, read-only freshness checks for the local repository index."""

from __future__ import annotations

import copy
import sqlite3
from .metadata_db import connect_metadata
import time
from pathlib import Path
from typing import Any

from .repo_budget import BudgetConnection, bounded_operation, budgeted, checkpoint
from .scanner import INDEX_VERSION, iter_project_files
import os
from .repo_files import open_repo_file, stat_mtime
from .utils import db_path, relative_path


_CACHE_TTL_SECONDS = 2.0
_HEALTH_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_PATH_SAMPLE_LIMIT = 5


@bounded_operation
def index_readiness(root: Path, *, use_cache: bool = True) -> dict[str, Any]:
    """Return index availability and lightweight filesystem drift metadata.

    The check compares paths, sizes and mtimes without hashing the whole project.
    A short cache keeps consecutive MCP calls cheap while still surfacing changes
    made during a normal agent session.
    """

    root = root.resolve()
    database = db_path(root)
    if not database.is_file():
        return _unavailable(
            "missing",
            "init-agent index not found. Run: init-agent run --overview --markdown",
        )

    try:
        database_mtime = database.stat().st_mtime_ns
    except OSError as exc:
        return _unavailable("error", f"init-agent index could not be inspected: {exc}")

    cache_key = (str(root), database_mtime)
    now = time.monotonic()
    if use_cache:
        cached = _HEALTH_CACHE.get(cache_key)
        if cached and now - cached[0] <= _CACHE_TTL_SECONDS:
            result = copy.deepcopy(cached[1])
            result["health"]["cached"] = True
            return result

    result = _inspect_index(root, database)
    _HEALTH_CACHE.clear()
    _HEALTH_CACHE[cache_key] = (now, copy.deepcopy(result))
    return result


def clear_index_health_cache() -> None:
    """Clear the process-local freshness cache, primarily for tests."""

    _HEALTH_CACHE.clear()


def _inspect_index(root: Path, database: Path) -> dict[str, Any]:
    conn: sqlite3.Connection | None = None
    try:
        conn = connect_metadata(root, readonly=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT path, size, modified_at FROM files ORDER BY path"
        ).fetchall()
        version_row = conn.execute(
            "SELECT value FROM project_meta WHERE key = 'index_version'"
        ).fetchone()
    except sqlite3.Error as exc:
        return _unavailable("error", f"init-agent index could not be read: {exc}")
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        return _unavailable(
            "empty",
            "init-agent index is empty. Run: init-agent run --overview --markdown",
        )

    indexed = {
        str(row["path"]): {
            "size": int(row["size"] or 0),
            "modified_at": str(row["modified_at"] or ""),
        }
        for row in budgeted(rows)
    }
    real_files: dict[str, Path] = {}
    for path in iter_project_files(root):
        checkpoint()
        try:
            real_files[relative_path(path, root)] = path
        except (OSError, ValueError):
            continue

    indexed_paths = set(indexed)
    real_paths = set(real_files)
    missing = sorted(indexed_paths - real_paths)
    unindexed = sorted(real_paths - indexed_paths)
    changed: list[str] = []
    for rel_path in sorted(indexed_paths & real_paths):
        checkpoint()
        path = real_files[rel_path]
        try:
            with open_repo_file(root, rel_path) as handle:
                stat = os.fstat(handle.fileno())
                current_mtime = stat_mtime(stat)
        except OSError:
            missing.append(rel_path)
            continue
        record = indexed[rel_path]
        if stat.st_size != record["size"] or current_mtime != record["modified_at"]:
            changed.append(rel_path)

    index_version = str(version_row["value"]) if version_row else None
    version_stale = index_version != INDEX_VERSION
    stale = bool(changed or missing or unindexed or version_stale)
    warnings: list[str] = []
    if version_stale:
        warnings.append("init-agent index uses an older extractor. Run: init-agent map")
    if changed or missing or unindexed:
        warnings.append(
            "init-agent index may be stale: "
            f"{len(changed)} changed, {len(missing)} removed, {len(unindexed)} unindexed files. "
            "Run: init-agent map"
        )

    health = {
        "status": "stale" if stale else "ready",
        "indexed_file_count": len(indexed_paths),
        "checked_file_count": len(real_paths),
        "changed_count": len(changed),
        "missing_count": len(missing),
        "unindexed_count": len(unindexed),
        "changed_paths": changed[:_PATH_SAMPLE_LIMIT],
        "missing_paths": missing[:_PATH_SAMPLE_LIMIT],
        "unindexed_paths": unindexed[:_PATH_SAMPLE_LIMIT],
        "paths_truncated": {
            "changed": len(changed) > _PATH_SAMPLE_LIMIT,
            "missing": len(missing) > _PATH_SAMPLE_LIMIT,
            "unindexed": len(unindexed) > _PATH_SAMPLE_LIMIT,
        },
        "index_version": index_version,
        "current_index_version": INDEX_VERSION,
        "cached": False,
        "check": "path_size_mtime",
    }
    return {"ready": True, "warnings": warnings, "health": health}


def _unavailable(status: str, warning: str) -> dict[str, Any]:
    return {
        "ready": False,
        "warnings": [warning],
        "health": {
            "status": status,
            "indexed_file_count": 0,
            "checked_file_count": 0,
            "changed_count": 0,
            "missing_count": 0,
            "unindexed_count": 0,
            "changed_paths": [],
            "missing_paths": [],
            "unindexed_paths": [],
            "paths_truncated": {"changed": False, "missing": False, "unindexed": False},
            "index_version": None,
            "current_index_version": INDEX_VERSION,
            "cached": False,
            "check": "path_size_mtime",
        },
    }
