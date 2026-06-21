"""Local orientation feedback storage and scoring helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import utc_now


RATINGS = {"crucial", "useful", "neutral", "noisy", "missing"}
SOURCES = {"user", "agent", "benchmark"}
POSITIVE_RATINGS = {"crucial", "useful"}
NEGATIVE_RATINGS = {"noisy"}
RATING_WEIGHTS = {
    "crucial": 24.0,
    "useful": 10.0,
    "neutral": 0.0,
    "noisy": -3.0,
    "missing": 0.0,
}
MIN_SIMILARITY = 0.25
MAX_POSITIVE_BOOST = 30.0
MAX_NEGATIVE_PENALTY = -5.0


def add_feedback(root: Path, query: str, path: str, rating: str, reason: str = "", source: str = "agent") -> dict[str, Any]:
    normalized_rating = rating.lower().strip()
    normalized_source = source.lower().strip()
    if normalized_rating not in RATINGS:
        raise ValueError(f"rating must be one of: {', '.join(sorted(RATINGS))}")
    if normalized_source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    tokens = tokenize_query(query)
    record = {
        "query": query,
        "query_tokens_json": json.dumps(tokens, sort_keys=True),
        "path": _normalize_path(path),
        "rating": normalized_rating,
        "reason": reason,
        "source": normalized_source,
        "created_at": utc_now(),
    }
    with GraphStore(root) as store:
        store.initialize()
        cursor = store.connection.execute(
            """
            INSERT INTO orientation_feedback(query, query_tokens_json, path, rating, reason, source, created_at)
            VALUES(:query, :query_tokens_json, :path, :rating, :reason, :source, :created_at)
            """,
            record,
        )
        store.connection.commit()
        record["id"] = int(cursor.lastrowid)
    return record


def list_feedback(root: Path, query: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    clauses = []
    params: list[str] = []
    if query:
        clauses.append("query = ?")
        params.append(query)
    if path:
        clauses.append("path = ?")
        params.append(_normalize_path(path))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            f"""
            SELECT id, query, query_tokens_json, path, rating, reason, source, created_at
            FROM orientation_feedback
            {where}
            ORDER BY id DESC
            """,
            params,
        ).fetchall()
    return [_row_to_feedback(row) for row in rows]


def clear_feedback(root: Path, query: str | None = None, path: str | None = None, all_items: bool = False) -> int:
    clauses = []
    params: list[str] = []
    if query:
        clauses.append("query = ?")
        params.append(query)
    if path:
        clauses.append("path = ?")
        params.append(_normalize_path(path))
    if not all_items and not clauses:
        raise ValueError("use --all, --query or --path to choose feedback to clear")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with GraphStore(root) as store:
        store.initialize()
        cursor = store.connection.execute(f"DELETE FROM orientation_feedback {where}", params)
        store.connection.commit()
        return int(cursor.rowcount)


def export_feedback(root: Path) -> dict[str, Any]:
    return {"feedback": list_feedback(root)}


def import_feedback(root: Path, payload: Any) -> int:
    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("feedback", [])
    if not isinstance(items, list):
        raise ValueError("feedback import must be a list or an object with a feedback list")
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        add_feedback(
            root,
            str(item.get("query") or ""),
            str(item.get("path") or ""),
            str(item.get("rating") or "neutral"),
            str(item.get("reason") or ""),
            str(item.get("source") or "agent"),
        )
        count += 1
    return count


def feedback_signals(root: Path, query_tokens: list[str], indexed_paths: set[str]) -> dict[str, dict[str, Any]]:
    query_token_set = set(query_tokens)
    if not query_token_set:
        return {}
    signals: dict[str, dict[str, Any]] = {}
    for item in list_feedback(root):
        path = str(item["path"])
        if path not in indexed_paths:
            continue
        item_tokens = set(item.get("query_tokens") or [])
        similarity = _jaccard(query_token_set, item_tokens)
        if similarity < MIN_SIMILARITY:
            continue
        rating = str(item["rating"])
        contribution = RATING_WEIGHTS.get(rating, 0.0) * similarity
        signal = signals.setdefault(
            path,
            {
                "boost": 0.0,
                "penalty": 0.0,
                "positive": set(),
                "negative": set(),
                "items": [],
            },
        )
        if contribution > 0:
            signal["boost"] = min(MAX_POSITIVE_BOOST, float(signal["boost"]) + contribution)
            signal["positive"].add(rating)
        elif contribution < 0:
            signal["penalty"] = max(MAX_NEGATIVE_PENALTY, float(signal["penalty"]) + contribution)
            signal["negative"].add(rating)
        signal["items"].append(item)
    return signals


def _row_to_feedback(row: Any) -> dict[str, Any]:
    try:
        tokens = json.loads(row["query_tokens_json"])
    except Exception:
        tokens = []
    return {
        "id": int(row["id"]),
        "query": row["query"],
        "query_tokens": tokens if isinstance(tokens, list) else [],
        "path": row["path"],
        "rating": row["rating"],
        "reason": row["reason"] or "",
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


def _normalize_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./")
