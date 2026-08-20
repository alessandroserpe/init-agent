"""Privacy-preserving ingestion for observable agent trajectory events."""

from __future__ import annotations

import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .utils import db_path, normalize_repo_path


CODEX_HOOK_EVENTS = {
    "SessionStart",
    "SessionEnd",
    "PreToolUse",
    "PostToolUse",
    "SubagentStart",
    "SubagentStop",
    "Stop",
}

TRAJECTORY_EVENT_LIMIT = 5000

_PATH_KEYS = {"path", "file", "filename", "cwd", "root", "workdir", "workdir_path"}
_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def ingest_codex_hook(
    root: Path,
    payload: dict[str, Any],
    *,
    source: str = "codex_hook",
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Normalize and store one Codex hook event without raw conversational data."""

    if not db_path(root).is_file():
        return {"recorded": False, "status": "not_initialized", "source": source}
    if not isinstance(payload, dict):
        raise ValueError("trajectory payload must be a JSON object")

    event_name = _bounded_text(payload.get("hook_event_name"), 80)
    if event_name not in CODEX_HOOK_EVENTS:
        raise ValueError(f"unsupported Codex hook event: {event_name or '<missing>'}")
    external_session_id = _bounded_text(payload.get("session_id"), 200)
    if not external_session_id:
        raise ValueError("session_id is required")

    now = recorded_at or _utc_now_ms()
    model = _bounded_text(payload.get("model"), 120)
    cwd = _safe_cwd(root, payload.get("cwd"))
    turn_id = _bounded_text(payload.get("turn_id"), 200)
    tool_name = _bounded_text(payload.get("tool_name"), 200)
    tool_use_id = _bounded_text(payload.get("tool_use_id"), 200)
    agent_id = _bounded_text(payload.get("agent_id"), 200)
    agent_type = _bounded_text(payload.get("agent_type"), 120)
    status = _event_status(event_name, payload)
    metadata = _event_metadata(root, event_name, payload)
    event_key = _event_key(event_name, turn_id, tool_use_id, agent_id)

    with GraphStore(root) as store:
        schema_ready = store.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trajectory_events'"
        ).fetchone()
        if schema_ready is None:
            store.initialize()
        store.connection.execute("PRAGMA busy_timeout = 1500")
        store.connection.execute("BEGIN IMMEDIATE")
        session_id = _upsert_session(
            store,
            source=source,
            external_session_id=external_session_id,
            cwd=cwd,
            model=model,
            event_name=event_name,
            payload=payload,
            now=now,
        )
        duration_ms = _paired_duration_ms(store, session_id, event_name, tool_use_id, now)
        existing = (
            store.connection.execute(
                "SELECT id, duration_ms FROM trajectory_events WHERE session_id = ? AND event_key = ?",
                (session_id, event_key),
            ).fetchone()
            if event_key
            else None
        )
        if existing is not None:
            return {
                "recorded": False,
                "status": "duplicate",
                "source": source,
                "session_id": external_session_id,
                "event_id": int(existing["id"]),
                "event_name": event_name,
                "duration_ms": existing["duration_ms"],
            }
        cursor = store.connection.execute(
            """
            INSERT INTO trajectory_events(
                session_id, turn_id, event_name, event_key, tool_name, tool_use_id,
                agent_id, agent_type, status, duration_ms, metadata_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                turn_id,
                event_name,
                event_key,
                tool_name,
                tool_use_id,
                agent_id,
                agent_type,
                status,
                duration_ms,
                json.dumps(metadata, sort_keys=True),
                now,
            ),
        )
        _prune_events(store)
        store.connection.commit()

    return {
        "recorded": True,
        "status": "recorded",
        "source": source,
        "session_id": external_session_id,
        "event_id": int(cursor.lastrowid),
        "event_name": event_name,
        "duration_ms": duration_ms,
    }


def find_initialized_trajectory_root(start: Path | str | None) -> Path | None:
    """Find the nearest existing init-agent database without creating metadata."""

    candidate = Path(start or Path.cwd()).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        return None
    if candidate.is_file():
        candidate = candidate.parent
    for current in (candidate, *candidate.parents):
        if db_path(current).is_file():
            return current
    return None


def _upsert_session(
    store: GraphStore,
    *,
    source: str,
    external_session_id: str,
    cwd: str,
    model: str,
    event_name: str,
    payload: dict[str, Any],
    now: str,
) -> int:
    row = store.connection.execute(
        "SELECT id, started_at FROM trajectory_sessions WHERE source = ? AND external_session_id = ?",
        (source, external_session_id),
    ).fetchone()
    end_reason = _bounded_text(payload.get("reason"), 80) if event_name == "SessionEnd" else ""
    if row is None:
        cursor = store.connection.execute(
            """
            INSERT INTO trajectory_sessions(
                source, external_session_id, cwd, model, started_at, ended_at,
                end_reason, first_event_at, last_event_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                external_session_id,
                cwd,
                model,
                now,
                now if event_name == "SessionEnd" else None,
                end_reason or None,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    session_id = int(row["id"])
    store.connection.execute(
        """
        UPDATE trajectory_sessions
        SET cwd = COALESCE(NULLIF(?, ''), cwd),
            model = COALESCE(NULLIF(?, ''), model),
            ended_at = CASE
                WHEN ? = 'SessionStart' THEN NULL
                WHEN ? = 'SessionEnd' THEN ?
                ELSE ended_at
            END,
            end_reason = CASE
                WHEN ? = 'SessionStart' THEN NULL
                WHEN ? = 'SessionEnd' THEN ?
                ELSE end_reason
            END,
            last_event_at = ?
        WHERE id = ?
        """,
        (
            cwd,
            model,
            event_name,
            event_name,
            now,
            event_name,
            event_name,
            end_reason or None,
            now,
            session_id,
        ),
    )
    return session_id


def _paired_duration_ms(
    store: GraphStore,
    session_id: int,
    event_name: str,
    tool_use_id: str,
    now: str,
) -> int | None:
    if event_name != "PostToolUse" or not tool_use_id:
        return None
    row = store.connection.execute(
        """
        SELECT created_at
        FROM trajectory_events
        WHERE session_id = ? AND tool_use_id = ? AND event_name = 'PreToolUse'
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id, tool_use_id),
    ).fetchone()
    if row is None:
        return None
    try:
        start = datetime.fromisoformat(str(row["created_at"]))
        finish = datetime.fromisoformat(now)
    except ValueError:
        return None
    return max(0, int((finish - start).total_seconds() * 1000))


def _event_metadata(root: Path, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"capture": "redacted_metadata_v1"}
    if event_name == "SessionStart":
        metadata["start_source"] = _bounded_text(payload.get("source"), 80)
    elif event_name == "SessionEnd":
        metadata["reason"] = _bounded_text(payload.get("reason"), 80)
    elif event_name == "PreToolUse":
        metadata["tool_input"] = _summarize_tool_input(root, payload.get("tool_name"), payload.get("tool_input"))
    elif event_name == "PostToolUse":
        metadata["tool_input"] = _summarize_tool_input(root, payload.get("tool_name"), payload.get("tool_input"))
        metadata["tool_response"] = _summarize_tool_response(payload.get("tool_response"))
    elif event_name in {"SubagentStart", "SubagentStop"}:
        metadata["permission_mode"] = _bounded_text(payload.get("permission_mode"), 80)
        if event_name == "SubagentStop":
            metadata["last_message_chars"] = _text_size(payload.get("last_assistant_message"))
    elif event_name == "Stop":
        metadata["last_message_chars"] = _text_size(payload.get("last_assistant_message"))
        metadata["stop_hook_active"] = bool(payload.get("stop_hook_active"))
    return metadata


def _summarize_tool_input(root: Path, tool_name: Any, value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": type(value).__name__,
        "size_chars": _json_size(value),
    }
    if not isinstance(value, dict):
        return summary
    summary["keys"] = sorted(str(key)[:80] for key in value)[:24]
    paths = _extract_paths(root, value)
    command = value.get("command")
    normalized_tool = _bounded_text(tool_name, 200)
    if isinstance(command, str):
        summary["command_name"] = _command_name(command)
        summary["command_chars"] = len(command)
        if normalized_tool == "apply_patch":
            paths.extend(_safe_repo_path(root, path, require_exists=False) for path in _PATCH_PATH.findall(command))
    summary["paths"] = sorted({path for path in paths if path})[:32]
    return summary


def _summarize_tool_response(value: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "type": type(value).__name__,
        "size_chars": _json_size(value),
    }
    if isinstance(value, dict):
        summary["keys"] = sorted(str(key)[:80] for key in value)[:24]
        if isinstance(value.get("exit_code"), int):
            summary["exit_code"] = int(value["exit_code"])
        if isinstance(value.get("isError"), bool):
            summary["is_error"] = bool(value["isError"])
    return summary


def _extract_paths(root: Path, value: Any, key: str = "", depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    if isinstance(value, dict):
        paths: list[str] = []
        for child_key, child in value.items():
            paths.extend(_extract_paths(root, child, str(child_key).lower(), depth + 1))
        return paths
    if isinstance(value, list):
        paths = []
        for child in value[:50]:
            paths.extend(_extract_paths(root, child, key, depth + 1))
        return paths
    if isinstance(value, str) and (key in _PATH_KEYS or key.endswith("_path") or key.endswith("_file")):
        return [_safe_repo_path(root, value, require_exists=True)]
    return []


def _safe_repo_path(root: Path, value: Any, *, require_exists: bool) -> str:
    text = _bounded_text(value, 500).strip()
    if not text:
        return ""
    if any(character in text for character in ("\x00", "\n", "\r")) or "://" in text:
        return ""
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return "<outside-repository>"
    else:
        relative = normalize_repo_path(text)
    normalized = Path(relative).as_posix()
    relative_path = Path(normalized)
    if not normalized or ".." in relative_path.parts:
        return "<outside-repository>"
    if require_exists and not (root / relative_path).exists():
        return ""
    return normalized


def _safe_cwd(root: Path, value: Any) -> str:
    path = _safe_repo_path(root, value, require_exists=True)
    return "." if path == "" else path


def _command_name(command: str) -> str:
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.strip().split()
    while parts and "=" in parts[0] and not parts[0].startswith(("/", "./")):
        parts.pop(0)
    return Path(parts[0]).name[:120] if parts else ""


def _event_status(event_name: str, payload: dict[str, Any]) -> str:
    if event_name == "PreToolUse":
        return "started"
    if event_name != "PostToolUse":
        return "observed"
    response = payload.get("tool_response")
    if isinstance(response, dict):
        if response.get("isError") is True:
            return "error"
        exit_code = response.get("exit_code")
        if isinstance(exit_code, int) and exit_code != 0:
            return "error"
    return "success"


def _event_key(event_name: str, turn_id: str, tool_use_id: str, agent_id: str) -> str:
    if tool_use_id:
        return f"{event_name}:tool:{tool_use_id}"
    if agent_id:
        return f"{event_name}:agent:{agent_id}"
    if turn_id:
        return f"{event_name}:turn:{turn_id}"
    return ""


def _prune_events(store: GraphStore) -> None:
    store.connection.execute(
        """
        DELETE FROM trajectory_events
        WHERE id NOT IN (
            SELECT id FROM trajectory_events ORDER BY id DESC LIMIT ?
        )
        """,
        (TRAJECTORY_EVENT_LIMIT,),
    )
    store.connection.execute(
        "DELETE FROM trajectory_sessions WHERE id NOT IN (SELECT DISTINCT session_id FROM trajectory_events)"
    )


def _bounded_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return str(value)[:limit]


def _text_size(value: Any) -> int:
    return len(value) if isinstance(value, str) else 0


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _utc_now_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
