"""Local agent memory notes tied to repository files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import utc_now


SOURCES = {"agent", "user", "benchmark"}
EVIDENCE_TYPES = {"read_full_file", "read_excerpt", "manifest_only", "inferred_from_graph"}


def add_note(
    root: Path,
    path: str,
    note: str,
    topic: str = "",
    query: str = "",
    source: str = "agent",
    evidence: str = "read_excerpt",
) -> dict[str, Any]:
    normalized_source = source.lower().strip()
    if normalized_source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    normalized_evidence = evidence.lower().strip() or "read_excerpt"
    if normalized_evidence not in EVIDENCE_TYPES:
        raise ValueError(f"evidence must be one of: {', '.join(sorted(EVIDENCE_TYPES))}")
    normalized_path = _normalize_path(path)
    clean_note = note.strip()
    if not clean_note:
        raise ValueError("note is required")
    token_text = " ".join([normalized_path, topic, query, normalized_evidence, clean_note])
    tokens = tokenize_query(token_text)
    record = {
        "path": normalized_path,
        "topic": topic.strip(),
        "query": query.strip(),
        "note": clean_note,
        "note_tokens_json": json.dumps(tokens, sort_keys=True),
        "file_sha256": None,
        "evidence": normalized_evidence,
        "source": normalized_source,
        "created_at": utc_now(),
    }
    with GraphStore(root) as store:
        store.initialize()
        record["file_sha256"] = _file_sha256(store, normalized_path)
        cursor = store.connection.execute(
            """
            INSERT INTO agent_notes(path, topic, query, note, note_tokens_json, file_sha256, evidence, source, created_at)
            VALUES(:path, :topic, :query, :note, :note_tokens_json, :file_sha256, :evidence, :source, :created_at)
            """,
            record,
        )
        store.connection.commit()
        record["id"] = int(cursor.lastrowid)
    return _record_to_note(record)


def list_notes(
    root: Path,
    path: str | None = None,
    topic: str | None = None,
    stale_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    bounded_limit = max(1, min(limit, 100))
    clauses = []
    params: list[Any] = []
    if path:
        clauses.append("path = ?")
        params.append(_normalize_path(path))
    if topic:
        clauses.append("topic = ?")
        params.append(topic.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    row_limit = 500 if stale_only else bounded_limit
    params.append(row_limit)
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            f"""
            SELECT id, path, topic, query, note, note_tokens_json, file_sha256, evidence, source, created_at
            FROM agent_notes
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        current_hashes = store.file_hashes()
    notes = [_with_staleness(_row_to_note(row), current_hashes) for row in rows]
    if stale_only:
        notes = [note for note in notes if note.get("stale") is not False]
    return notes[:bounded_limit]


def delete_note(root: Path, note_id: int) -> dict[str, Any]:
    if note_id <= 0:
        raise ValueError("note id must be positive")
    with GraphStore(root) as store:
        store.initialize()
        row = store.connection.execute(
            """
            SELECT id, path, topic, query, note, note_tokens_json, file_sha256, evidence, source, created_at
            FROM agent_notes
            WHERE id = ?
            """,
            (note_id,),
        ).fetchone()
        if row is None:
            return {"deleted": False, "id": note_id, "note": None}
        current_hashes = store.file_hashes()
        note = _with_staleness(_row_to_note(row), current_hashes)
        store.connection.execute("DELETE FROM agent_notes WHERE id = ?", (note_id,))
        store.connection.commit()
    return {"deleted": True, "id": note_id, "note": _public_note(note)}


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
        "file_sha256": row["file_sha256"] or "",
        "evidence": row["evidence"] or "unknown",
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _record_to_note(record: dict[str, Any]) -> dict[str, Any]:
    tokens = json.loads(str(record["note_tokens_json"]))
    file_sha256 = str(record.get("file_sha256") or "")
    return {
        "id": int(record["id"]),
        "path": record["path"],
        "topic": record["topic"],
        "query": record["query"],
        "note": record["note"],
        "tokens": tokens if isinstance(tokens, list) else [],
        "file_sha256": file_sha256,
        "current_file_sha256": file_sha256,
        "stale": False if file_sha256 else True,
        "stale_reason": "" if file_sha256 else "file is not indexed",
        "evidence": record["evidence"],
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
        "file_sha256": note.get("file_sha256", ""),
        "current_file_sha256": note.get("current_file_sha256", ""),
        "stale": note.get("stale"),
        "stale_reason": note.get("stale_reason", ""),
        "evidence": note.get("evidence", "unknown"),
        "source": note["source"],
        "created_at": note["created_at"],
    }


def _file_sha256(store: GraphStore, path: str) -> str | None:
    row = store.connection.execute("SELECT sha256 FROM files WHERE path = ?", (path,)).fetchone()
    return str(row["sha256"]) if row and row["sha256"] else None


def _with_staleness(note: dict[str, Any], current_hashes: dict[str, str]) -> dict[str, Any]:
    path = str(note["path"])
    stored_hash = str(note.get("file_sha256") or "")
    current_hash = str(current_hashes.get(path) or "")
    if not current_hash:
        stale = True
        reason = "file is not indexed"
    elif not stored_hash:
        stale = None
        reason = "memory predates file hash tracking"
    elif stored_hash != current_hash:
        stale = True
        reason = "file changed since memory was recorded"
    else:
        stale = False
        reason = ""
    return {
        **note,
        "current_file_sha256": current_hash,
        "stale": stale,
        "stale_reason": reason,
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
