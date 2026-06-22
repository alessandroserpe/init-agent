"""Local agent memory notes tied to repository files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import utc_now


SOURCES = {"agent", "user", "benchmark"}


def add_note(
    root: Path,
    path: str,
    note: str,
    topic: str = "",
    query: str = "",
    source: str = "agent",
) -> dict[str, Any]:
    normalized_source = source.lower().strip()
    if normalized_source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    normalized_path = _normalize_path(path)
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("note is required")
    token_text = " ".join([normalized_path, topic, query, clean_note])
    tokens = tokenize_query(token_text)
    record = {
        "path": normalized_path,
        "topic": topic.strip(),
        "query": query.strip(),
        "note": clean_note,
        "note_tokens_json": json.dumps(tokens, sort_keys=True),
        "source": normalized_source,
        "created_at": utc_now(),
    }
    with GraphStore(root) as store:
        store.initialize()
        cursor = store.connection.execute(
            """
            INSERT INTO agent_notes(path, topic, query, note, note_tokens_json, source, created_at)
            VALUES(:path, :topic, :query, :note, :note_tokens_json, :source, :created_at)
            """,
            record,
        )
        store.connection.commit()
        record["id"] = int(cursor.lastrowid)
    return _record_to_note(record)


def list_notes(root: Path, path: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, 100))
    clauses = []
    params: list[Any] = []
    if path:
        clauses.append("path = ?")
        params.append(_normalize_path(path))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(bounded_limit)
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            f"""
            SELECT id, path, topic, query, note, note_tokens_json, source, created_at
            FROM agent_notes
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_row_to_note(row) for row in rows]


def search_notes(root: Path, query: str, path: str | None = None, limit: int = 10) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 50))
    query_tokens = tokenize_query(query)
    query_set = set(query_tokens)
    notes = list_notes(root, path=path, limit=500)
    matches = []
    for note in notes:
        note_tokens = set(note.get("tokens") or [])
        score = _score(query_set, note_tokens, query, note)
        if score <= 0:
            continue
        matches.append({**_public_note(note), "score": round(score, 4)})
    matches.sort(key=lambda item: (-float(item["score"]), -int(item["id"])))
    return {
        "query": query,
        "query_tokens": query_tokens,
        "path": _normalize_path(path) if path else None,
        "matches": matches[:bounded_limit],
    }


def _row_to_note(row: Any) -> dict[str, Any]:
    try:
        tokens = json.loads(row["note_tokens_json"])
    except Exception:
        tokens = []
    return {
        "id": int(row["id"]),
        "path": row["path"],
        "topic": row["topic"] or "",
        "query": row["query"] or "",
        "note": row["note"],
        "tokens": tokens if isinstance(tokens, list) else [],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _record_to_note(record: dict[str, Any]) -> dict[str, Any]:
    tokens = json.loads(str(record["note_tokens_json"]))
    return {
        "id": int(record["id"]),
        "path": record["path"],
        "topic": record["topic"],
        "query": record["query"],
        "note": record["note"],
        "tokens": tokens if isinstance(tokens, list) else [],
        "source": record["source"],
        "created_at": record["created_at"],
    }


def _public_note(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note["id"],
        "path": note["path"],
        "topic": note["topic"],
        "query": note["query"],
        "note": note["note"],
        "source": note["source"],
        "created_at": note["created_at"],
    }


def _score(query_tokens: set[str], note_tokens: set[str], query: str, note: dict[str, Any]) -> float:
    if not query_tokens:
        return 0.0
    overlap = len(query_tokens.intersection(note_tokens))
    score = overlap / max(1, len(query_tokens))
    query_lower = query.lower()
    path = str(note.get("path") or "").lower()
    topic = str(note.get("topic") or "").lower()
    if query_lower and query_lower in topic:
        score += 0.5
    if any(token and token in path for token in query_tokens):
        score += 0.2
    return score


def _normalize_path(path: str | None) -> str:
    return Path(path or "").as_posix().lstrip("./")
