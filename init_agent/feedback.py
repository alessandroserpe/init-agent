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
SOURCE_WEIGHTS = {
    "agent": 1.0,
    "benchmark": 1.1,
    "user": 1.2,
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


def explain_feedback(root: Path, query: str, include_all: bool = False) -> dict[str, Any]:
    query_tokens = tokenize_query(query)
    query_token_set = set(query_tokens)
    indexed_paths = _indexed_paths(root)
    signals = feedback_signals(root, query_tokens, indexed_paths)

    by_path: dict[str, list[dict[str, Any]]] = {}
    ignored: list[dict[str, Any]] = []
    for item in list_feedback(root):
        path = str(item["path"])
        item_tokens = set(item.get("query_tokens") or [])
        similarity = _jaccard(query_token_set, item_tokens)
        rating = str(item["rating"])
        source = str(item.get("source") or "agent")
        contribution = _feedback_contribution(item, similarity)
        matched = path in indexed_paths and similarity >= MIN_SIMILARITY
        explanation_item = {
            "id": item["id"],
            "query": item["query"],
            "path": path,
            "rating": rating,
            "source": source,
            "source_weight": SOURCE_WEIGHTS.get(source, 1.0),
            "reason": item["reason"],
            "similarity": round(similarity, 4),
            "contribution": round(contribution, 4),
            "matched": matched,
        }
        if matched:
            by_path.setdefault(path, []).append(explanation_item)
        elif include_all:
            ignored_reason = "path is not indexed" if path not in indexed_paths else "similarity below threshold"
            ignored.append({**explanation_item, "ignored_reason": ignored_reason})

    signal_rows = []
    for path, signal in signals.items():
        items = sorted(by_path.get(path, []), key=lambda item: abs(float(item["contribution"])), reverse=True)
        signal_rows.append(
            {
                "path": path,
                "boost": round(float(signal.get("boost", 0.0)), 4),
                "penalty": round(float(signal.get("penalty", 0.0)), 4),
                "net": round(float(signal.get("boost", 0.0)) + float(signal.get("penalty", 0.0)), 4),
                "items": items,
            }
        )
    signal_rows.sort(key=lambda item: abs(float(item["net"])), reverse=True)
    ignored.sort(key=lambda item: abs(float(item["contribution"])), reverse=True)
    return {
        "query": query,
        "query_tokens": query_tokens,
        "min_similarity": MIN_SIMILARITY,
        "signals": signal_rows,
        "ignored": ignored,
    }


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
        contribution = _feedback_contribution(item, similarity)
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


def _indexed_paths(root: Path) -> set[str]:
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute("SELECT path FROM files").fetchall()
    return {str(row["path"]) for row in rows}


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


def _feedback_contribution(item: dict[str, Any], similarity: float) -> float:
    rating = str(item.get("rating") or "")
    source = str(item.get("source") or "agent")
    return RATING_WEIGHTS.get(rating, 0.0) * SOURCE_WEIGHTS.get(source, 1.0) * similarity


def _normalize_path(path: str) -> str:
    return Path(path).as_posix().lstrip("./")
