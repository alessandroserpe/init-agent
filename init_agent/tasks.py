"""Local agent task/session memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .utils import ensure_agent_dir, utc_now


STATUSES = {"open", "in_progress", "blocked", "done"}
SOURCES = {"agent", "user", "benchmark"}


def add_task(
    root: Path,
    title: str,
    topic: str = "",
    summary: str = "",
    files: list[str] | None = None,
    status: str = "open",
    source: str = "agent",
) -> dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title is required")
    normalized_status = _normalize_status(status)
    normalized_source = _normalize_source(source)
    now = utc_now()
    record = {
        "title": clean_title,
        "status": normalized_status,
        "topic": topic.strip(),
        "summary": summary.strip(),
        "files_json": _json_list(_normalize_paths(files or [])),
        "memory_ids_json": _json_list([]),
        "feedback_ids_json": _json_list([]),
        "tests_json": _json_list([]),
        "remaining_json": _json_list([]),
        "source": normalized_source,
        "created_at": now,
        "updated_at": now,
        "closed_at": now if normalized_status == "done" else None,
    }
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        cursor = store.connection.execute(
            """
            INSERT INTO agent_tasks(
                title, status, topic, summary, files_json, memory_ids_json,
                feedback_ids_json, tests_json, remaining_json, source,
                created_at, updated_at, closed_at
            )
            VALUES(
                :title, :status, :topic, :summary, :files_json, :memory_ids_json,
                :feedback_ids_json, :tests_json, :remaining_json, :source,
                :created_at, :updated_at, :closed_at
            )
            """,
            record,
        )
        store.connection.commit()
        record["id"] = int(cursor.lastrowid)
    return _record_to_task(record, notes=[])


def list_tasks(
    root: Path,
    status: str | None = None,
    topic: str | None = None,
    include_done: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, 100))
    clauses = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(_normalize_status(status))
    elif not include_done:
        clauses.append("status != 'done'")
    if topic:
        clauses.append("topic = ?")
        params.append(topic.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(bounded_limit)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            f"""
            SELECT id, title, status, topic, summary, files_json, memory_ids_json,
                   feedback_ids_json, tests_json, remaining_json, source,
                   created_at, updated_at, closed_at
            FROM agent_tasks
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_task(row, notes=[]) for row in rows]


def get_task(root: Path, task_id: int) -> dict[str, Any] | None:
    if task_id <= 0:
        raise ValueError("task id must be positive")
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = _fetch_task_row(store, task_id)
        if row is None:
            return None
        notes = _fetch_task_notes(store, task_id)
    return _row_to_task(row, notes=notes)


def update_task(
    root: Path,
    task_id: int,
    status: str | None = None,
    topic: str | None = None,
    summary: str | None = None,
    files: list[str] | None = None,
    memory_ids: list[int] | None = None,
    feedback_ids: list[int] | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    if task_id <= 0:
        raise ValueError("task id must be positive")
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = _fetch_task_row(store, task_id)
        if row is None:
            return {"updated": False, "id": task_id, "task": None}
        task = _row_to_task(row, notes=[])
        updated_status = _normalize_status(status) if status is not None else task["status"]
        updated_source = _normalize_source(source) if source is not None else task["source"]
        now = utc_now()
        record = {
            "id": task_id,
            "title": task["title"],
            "status": updated_status,
            "topic": topic.strip() if topic is not None else task["topic"],
            "summary": summary.strip() if summary is not None else task["summary"],
            "files_json": _json_list(_merge_unique(task["files"], _normalize_paths(files or []))),
            "memory_ids_json": _json_list(_merge_unique(task["memory_ids"], memory_ids or [])),
            "feedback_ids_json": _json_list(_merge_unique(task["feedback_ids"], feedback_ids or [])),
            "tests_json": _json_list(_merge_unique(task["tests"], [item.strip() for item in tests or [] if item.strip()])),
            "remaining_json": _json_list(_merge_unique(task["remaining"], [item.strip() for item in remaining or [] if item.strip()])),
            "source": updated_source,
            "updated_at": now,
            "closed_at": now if updated_status == "done" and not task.get("closed_at") else task.get("closed_at"),
        }
        store.connection.execute(
            """
            UPDATE agent_tasks
            SET status = :status,
                topic = :topic,
                summary = :summary,
                files_json = :files_json,
                memory_ids_json = :memory_ids_json,
                feedback_ids_json = :feedback_ids_json,
                tests_json = :tests_json,
                remaining_json = :remaining_json,
                source = :source,
                updated_at = :updated_at,
                closed_at = :closed_at
            WHERE id = :id
            """,
            record,
        )
        store.connection.commit()
        row = _fetch_task_row(store, task_id)
        notes = _fetch_task_notes(store, task_id)
    return {"updated": True, "id": task_id, "task": _row_to_task(row, notes=notes) if row else None}


def add_task_note(
    root: Path,
    task_id: int,
    note: str,
    files: list[str] | None = None,
    memory_ids: list[int] | None = None,
    feedback_ids: list[int] | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    if task_id <= 0:
        raise ValueError("task id must be positive")
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("note is required")
    normalized_source = _normalize_source(source)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = _fetch_task_row(store, task_id)
        if row is None:
            return {"recorded": False, "id": task_id, "note": None, "task": None}
        now = utc_now()
        note_record = {
            "task_id": task_id,
            "note": clean_note,
            "files_json": _json_list(_normalize_paths(files or [])),
            "memory_ids_json": _json_list(memory_ids or []),
            "feedback_ids_json": _json_list(feedback_ids or []),
            "tests_json": _json_list([item.strip() for item in tests or [] if item.strip()]),
            "remaining_json": _json_list([item.strip() for item in remaining or [] if item.strip()]),
            "source": normalized_source,
            "created_at": now,
        }
        cursor = store.connection.execute(
            """
            INSERT INTO agent_task_notes(
                task_id, note, files_json, memory_ids_json, feedback_ids_json,
                tests_json, remaining_json, source, created_at
            )
            VALUES(
                :task_id, :note, :files_json, :memory_ids_json, :feedback_ids_json,
                :tests_json, :remaining_json, :source, :created_at
            )
            """,
            note_record,
        )
        existing = _row_to_task(row, notes=[])
        merged = {
            "id": task_id,
            "files_json": _json_list(_merge_unique(existing["files"], _normalize_paths(files or []))),
            "memory_ids_json": _json_list(_merge_unique(existing["memory_ids"], memory_ids or [])),
            "feedback_ids_json": _json_list(_merge_unique(existing["feedback_ids"], feedback_ids or [])),
            "tests_json": _json_list(_merge_unique(existing["tests"], [item.strip() for item in tests or [] if item.strip()])),
            "remaining_json": _json_list(_merge_unique(existing["remaining"], [item.strip() for item in remaining or [] if item.strip()])),
            "updated_at": now,
        }
        store.connection.execute(
            """
            UPDATE agent_tasks
            SET files_json = :files_json,
                memory_ids_json = :memory_ids_json,
                feedback_ids_json = :feedback_ids_json,
                tests_json = :tests_json,
                remaining_json = :remaining_json,
                updated_at = :updated_at
            WHERE id = :id
            """,
            merged,
        )
        store.connection.commit()
        note_record["id"] = int(cursor.lastrowid)
        row = _fetch_task_row(store, task_id)
        notes = _fetch_task_notes(store, task_id)
    return {
        "recorded": True,
        "id": task_id,
        "note": _record_to_task_note(note_record),
        "task": _row_to_task(row, notes=notes) if row else None,
    }


def close_task(
    root: Path,
    task_id: int,
    summary: str | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    return update_task(
        root,
        task_id,
        status="done",
        summary=summary,
        tests=tests,
        remaining=remaining,
        source=source,
    )


def _fetch_task_row(store: GraphStore, task_id: int) -> Any:
    return store.connection.execute(
        """
        SELECT id, title, status, topic, summary, files_json, memory_ids_json,
               feedback_ids_json, tests_json, remaining_json, source,
               created_at, updated_at, closed_at
        FROM agent_tasks
        WHERE id = ?
        """,
        (task_id,),
    ).fetchone()


def _fetch_task_notes(store: GraphStore, task_id: int) -> list[dict[str, Any]]:
    rows = store.connection.execute(
        """
        SELECT id, task_id, note, files_json, memory_ids_json, feedback_ids_json,
               tests_json, remaining_json, source, created_at
        FROM agent_task_notes
        WHERE task_id = ?
        ORDER BY id DESC
        """,
        (task_id,),
    ).fetchall()
    return [_row_to_task_note(row) for row in rows]


def _row_to_task(row: Any, notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "status": row["status"],
        "topic": row["topic"] or "",
        "summary": row["summary"] or "",
        "files": _load_list(row["files_json"]),
        "memory_ids": _load_list(row["memory_ids_json"]),
        "feedback_ids": _load_list(row["feedback_ids_json"]),
        "tests": _load_list(row["tests_json"]),
        "remaining": _load_list(row["remaining_json"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "closed_at": row["closed_at"] or "",
        "notes": notes,
    }


def _record_to_task(record: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "title": record["title"],
        "status": record["status"],
        "topic": record["topic"],
        "summary": record["summary"],
        "files": _load_list(record["files_json"]),
        "memory_ids": _load_list(record["memory_ids_json"]),
        "feedback_ids": _load_list(record["feedback_ids_json"]),
        "tests": _load_list(record["tests_json"]),
        "remaining": _load_list(record["remaining_json"]),
        "source": record["source"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "closed_at": record.get("closed_at") or "",
        "notes": notes,
    }


def _row_to_task_note(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "task_id": int(row["task_id"]),
        "note": row["note"],
        "files": _load_list(row["files_json"]),
        "memory_ids": _load_list(row["memory_ids_json"]),
        "feedback_ids": _load_list(row["feedback_ids_json"]),
        "tests": _load_list(row["tests_json"]),
        "remaining": _load_list(row["remaining_json"]),
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _record_to_task_note(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "task_id": int(record["task_id"]),
        "note": record["note"],
        "files": _load_list(record["files_json"]),
        "memory_ids": _load_list(record["memory_ids_json"]),
        "feedback_ids": _load_list(record["feedback_ids_json"]),
        "tests": _load_list(record["tests_json"]),
        "remaining": _load_list(record["remaining_json"]),
        "source": record["source"],
        "created_at": record["created_at"],
    }


def _normalize_status(status: str) -> str:
    normalized = status.lower().strip()
    if normalized not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
    return normalized


def _normalize_source(source: str) -> str:
    normalized = source.lower().strip()
    if normalized not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    return normalized


def _normalize_paths(paths: list[str]) -> list[str]:
    return [Path(path).as_posix().lstrip("./") for path in paths if path and path.strip()]


def _merge_unique(existing: list[Any], additions: list[Any]) -> list[Any]:
    result = list(existing)
    seen = {json.dumps(item, sort_keys=True) for item in result}
    for item in additions:
        marker = json.dumps(item, sort_keys=True)
        if marker not in seen:
            result.append(item)
            seen.add(marker)
    return result


def _json_list(items: list[Any]) -> str:
    return json.dumps(items, sort_keys=True)


def _load_list(value: str) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []
