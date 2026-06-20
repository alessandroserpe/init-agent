"""Read-only diagnostics for init-agent project readiness."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .git_reader import git_available, status_short
from .graph_store import SCHEMA
from .scanner import INDEX_VERSION, iter_project_files
from .utils import agent_dir, config_path, db_path, relative_path


REQUIRED_TABLES = {
    "project_meta",
    "files",
    "symbols",
    "relations",
    "git_commits",
    "git_commit_files",
    "runs",
    "term_stats",
}


def run_doctor(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    suggested_commands: list[str] = []
    stats = {"files": 0, "symbols": 0, "relations": 0, "git_commits": 0, "last_map": None}

    agent_exists = agent_dir(root).is_dir()
    database_exists = db_path(root).is_file()
    config_exists = config_path(root).is_file()
    has_git = (root / ".git").exists() and git_available(root)
    git_status = status_short(root) if has_git else []

    _add_check(checks, "agent_folder", agent_exists, "error", "Agent folder is present." if agent_exists else "Missing .agent folder.")
    _add_check(checks, "database", database_exists, "error", "Database is present." if database_exists else "Missing .agent/graph.sqlite.")
    _add_check(checks, "config", config_exists, "error", "Config is present." if config_exists else "Missing .agent/config.json.")
    _add_check(checks, "git_repository", True, "info", f"Git repository: {'yes' if has_git else 'no'}.")

    if not agent_exists or not database_exists:
        _suggest(suggested_commands, "init-agent init")
        return _finalize(checks, stats, warnings, suggested_commands)
    if not config_exists:
        _suggest(suggested_commands, "init-agent init")

    conn = None
    try:
        conn = sqlite3.connect(db_path(root))
        conn.row_factory = sqlite3.Row
        existing_tables = _table_names(conn)
        missing_tables = sorted(REQUIRED_TABLES - existing_tables)
        tables_ok = not missing_tables
        _add_check(
            checks,
            "sqlite_tables",
            tables_ok,
            "error",
            "All required SQLite tables are present."
            if tables_ok
            else f"Missing SQLite tables: {', '.join(missing_tables)}.",
        )
        if not tables_ok:
            _suggest(suggested_commands, "init-agent init")
            return _finalize(checks, stats, warnings, suggested_commands)

        stats = _stats(conn)
        indexed_paths = _indexed_paths(conn)
        index_version = _project_meta(conn, "index_version")
        git_run_indexed = _successful_run_exists(conn, "git")
    except sqlite3.Error as exc:
        _add_check(checks, "database_readable", False, "error", f"Database is not readable: {exc}.")
        _suggest(suggested_commands, "init-agent init")
        return _finalize(checks, stats, warnings, suggested_commands)
    finally:
        if conn is not None:
            conn.close()

    files_indexed_ok = stats["files"] > 0
    _add_check(
        checks,
        "files_indexed",
        files_indexed_ok,
        "error",
        f"Files indexed: {stats['files']}." if files_indexed_ok else "No files are indexed.",
    )
    _add_check(checks, "symbols", True, "info", f"Symbols: {stats['symbols']}.")
    _add_check(checks, "relations", True, "info", f"Relations: {stats['relations']}.")
    _add_check(checks, "git_commits", True, "info", f"Git commits indexed: {stats['git_commits']}.")
    if not files_indexed_ok:
        _suggest(suggested_commands, "init-agent map")

    if files_indexed_ok and index_version != INDEX_VERSION:
        message = "Index was created with an older extractor. Run: init-agent map"
        _add_warning(checks, warnings, "index_version", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "index_version", True, "info", "Index extractor version is current.")

    git_indexed = bool(has_git and (stats["git_commits"] > 0 or git_run_indexed))
    if has_git and not git_indexed:
        message = "Git repository detected but git timeline was not indexed. Run: init-agent git"
        _add_warning(checks, warnings, "git_indexed", message)
        _suggest(suggested_commands, "init-agent git")
    else:
        _add_check(checks, "git_indexed", True, "info", f"Git indexed: {'yes' if git_indexed else 'not needed'}.")

    if git_status:
        message = f"{len(git_status)} Git status entries are uncommitted."
        _add_warning(checks, warnings, "git_uncommitted_changes", message)
    else:
        _add_check(checks, "git_uncommitted_changes", True, "info", "No uncommitted Git changes detected.")

    real_paths = _real_project_paths(root)
    changed_after_map = _changed_after_last_map(root, indexed_paths, stats["last_map"])
    missing_indexed = sorted(path for path in indexed_paths if path not in real_paths)
    unindexed_real = sorted(path for path in real_paths if path not in indexed_paths)

    if changed_after_map:
        message = f"{len(changed_after_map)} files changed since last map. Run: init-agent map"
        _add_warning(checks, warnings, "files_changed_after_map", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "files_changed_after_map", True, "info", "No indexed files changed after last map.")

    if missing_indexed:
        message = f"{len(missing_indexed)} indexed files no longer exist. Run: init-agent map"
        _add_warning(checks, warnings, "indexed_files_missing", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "indexed_files_missing", True, "info", "No missing indexed files detected.")

    if unindexed_real:
        message = f"{len(unindexed_real)} project files are not indexed. Run: init-agent map"
        _add_warning(checks, warnings, "real_files_not_indexed", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "real_files_not_indexed", True, "info", "No unindexed project files detected.")

    return _finalize(checks, stats, warnings, suggested_commands)


def required_tables_from_schema() -> set[str]:
    """Expose required tables for tests and future schema checks."""

    return REQUIRED_TABLES | {
        line.split()[5]
        for line in SCHEMA.splitlines()
        if line.strip().upper().startswith("CREATE TABLE IF NOT EXISTS")
    }


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def _stats(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "files": _count(conn, "files"),
        "symbols": _count(conn, "symbols"),
        "relations": _count(conn, "relations"),
        "git_commits": _count(conn, "git_commits"),
        "last_map": _latest_map(conn),
    }


def _indexed_paths(conn: sqlite3.Connection) -> set[str]:
    return {row["path"] for row in conn.execute("SELECT path FROM files").fetchall()}


def _project_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM project_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _successful_run_exists(conn: sqlite3.Connection, command: str) -> bool:
    row = conn.execute("SELECT 1 FROM runs WHERE command = ? AND status = 'ok' LIMIT 1", (command,)).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"])


def _latest_map(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT finished_at FROM runs WHERE command = 'map' AND status = 'ok' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["finished_at"] if row else None


def _real_project_paths(root: Path) -> set[str]:
    paths = set()
    for path in iter_project_files(root):
        try:
            paths.add(relative_path(path, root))
        except ValueError:
            continue
    return paths


def _changed_after_last_map(root: Path, indexed_paths: set[str], last_map: str | None) -> list[str]:
    if not last_map:
        return []
    try:
        last_map_time = datetime.fromisoformat(last_map)
    except ValueError:
        return []
    if last_map_time.tzinfo is None:
        last_map_time = last_map_time.replace(tzinfo=timezone.utc)

    changed = []
    for rel_path in indexed_paths:
        path = root / rel_path
        if not path.exists():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified > last_map_time + timedelta(seconds=1):
            changed.append(rel_path)
    return sorted(changed)


def _add_check(checks: list[dict[str, Any]], name: str, ok: bool, severity: str, message: str) -> None:
    checks.append({"name": name, "ok": ok, "severity": "info" if ok else severity, "message": message})


def _add_warning(checks: list[dict[str, Any]], warnings: list[str], name: str, message: str) -> None:
    warnings.append(message)
    _add_check(checks, name, False, "warning", message)


def _suggest(commands: list[str], command: str) -> None:
    if command not in commands:
        commands.append(command)


def _finalize(
    checks: list[dict[str, Any]],
    stats: dict[str, Any],
    warnings: list[str],
    suggested_commands: list[str],
) -> dict[str, Any]:
    has_error = any(not check["ok"] and check["severity"] == "error" for check in checks)
    if has_error:
        status = "NOT_READY"
    elif warnings:
        status = "READY_WITH_WARNINGS"
    else:
        status = "READY"
    return {
        "status": status,
        "checks": checks,
        "stats": stats,
        "warnings": warnings,
        "suggested_commands": suggested_commands,
    }
