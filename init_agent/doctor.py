"""Read-only diagnostics for init-agent project readiness."""

from __future__ import annotations

import sqlite3
from .metadata_db import connect_metadata
from pathlib import Path
from typing import Any

from . import __version__
from .git_reader import git_available, status_short
from .graph_store import SCHEMA
from .index_health import index_readiness
from .scanner import INDEX_VERSION
from .skill_installer import codex_skill_status
from .updates import check_latest_release
from .utils import agent_dir, config_path, db_path


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


def run_doctor(
    root: Path,
    *,
    check_updates: bool = False,
    skill_root: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    suggested_commands: list[str] = []
    stats = {"files": 0, "symbols": 0, "relations": 0, "git_commits": 0, "last_map": None}
    environment: dict[str, Any] = {
        "version": __version__,
        "codex_skill": codex_skill_status(skill_root),
    }

    skill = environment["codex_skill"]
    if skill["status"] == "missing":
        _add_check(checks, "codex_skill", True, "info", "Codex skill is not installed (optional).")
    elif skill["current"]:
        _add_check(checks, "codex_skill", True, "info", f"Codex skill is current for init-agent {__version__}.")
    else:
        message = f"Codex skill is {skill['status']}. Run: init-agent sync"
        _add_warning(checks, warnings, "codex_skill", message)
        _suggest(suggested_commands, "init-agent sync")

    if check_updates:
        release = check_latest_release(__version__)
        environment["release"] = release
        if release["status"] == "update_available":
            message = f"init-agent {release['latest_version']} is available. Run: pipx upgrade init-agent"
            _add_warning(checks, warnings, "latest_release", message)
            _suggest(suggested_commands, "pipx upgrade init-agent")
        elif release["status"] in {"current", "ahead"}:
            _add_check(checks, "latest_release", True, "info", release["message"])
        else:
            _add_check(checks, "latest_release", False, "info", release["message"])

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
        return _finalize(checks, stats, warnings, suggested_commands, environment)
    if not config_exists:
        _suggest(suggested_commands, "init-agent init")

    conn = None
    try:
        conn = connect_metadata(root, readonly=True)
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
            return _finalize(checks, stats, warnings, suggested_commands, environment)

        stats = _stats(conn)
        index_version = _project_meta(conn, "index_version")
        git_run_indexed = _successful_run_exists(conn, "git")
    except sqlite3.Error as exc:
        _add_check(checks, "database_readable", False, "error", f"Database is not readable: {exc}.")
        _suggest(suggested_commands, "init-agent init")
        return _finalize(checks, stats, warnings, suggested_commands, environment)
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

    health = index_readiness(root, use_cache=False)["health"]
    changed_after_map = int(health.get("changed_count") or 0)
    missing_indexed = int(health.get("missing_count") or 0)
    unindexed_real = int(health.get("unindexed_count") or 0)

    if changed_after_map:
        message = f"{changed_after_map} files changed since last map. Run: init-agent map"
        _add_warning(checks, warnings, "files_changed_after_map", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "files_changed_after_map", True, "info", "No indexed files changed after last map.")

    if missing_indexed:
        message = f"{missing_indexed} indexed files no longer exist. Run: init-agent map"
        _add_warning(checks, warnings, "indexed_files_missing", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "indexed_files_missing", True, "info", "No missing indexed files detected.")

    if unindexed_real:
        message = f"{unindexed_real} project files are not indexed. Run: init-agent map"
        _add_warning(checks, warnings, "real_files_not_indexed", message)
        _suggest(suggested_commands, "init-agent map")
    else:
        _add_check(checks, "real_files_not_indexed", True, "info", "No unindexed project files detected.")

    return _finalize(checks, stats, warnings, suggested_commands, environment)


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
    environment: dict[str, Any],
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
        "environment": environment,
    }
