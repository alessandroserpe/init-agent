"""Persistent reading-plan tracking and feedback helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .feedback import add_feedback
from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import ensure_agent_dir, utc_now


SOURCES = {"agent", "user", "benchmark"}


def save_reading_plan(
    root: Path,
    query: str,
    plan_items: list[dict[str, Any]],
    read_budget: int,
    source: str = "agent",
) -> dict[str, Any]:
    normalized_source = _source(source)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        created_at = utc_now()
        cursor = store.connection.execute(
            """
            INSERT INTO reading_plans(query, query_tokens_json, read_budget, source, summary, finished_at, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query.strip(),
                json.dumps(tokenize_query(query), sort_keys=True),
                int(read_budget),
                normalized_source,
                "",
                None,
                created_at,
            ),
        )
        plan_id = int(cursor.lastrowid)
        store.connection.executemany(
            """
            INSERT INTO reading_plan_items(
                plan_id, path, rank, score, action, read_priority, read_budget_rank,
                confidence, sources_json, tags_json, reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan_id,
                    str(item.get("path") or ""),
                    int(item.get("rank") or 0),
                    float(item.get("score") or 0.0),
                    str(item.get("action") or ""),
                    str(item.get("read_priority") or ""),
                    item.get("read_budget_rank"),
                    str(item.get("confidence") or ""),
                    json.dumps(list(item.get("sources") or []), sort_keys=True),
                    json.dumps(list(item.get("tags") or []), sort_keys=True),
                    str(item.get("reason") or ""),
                )
                for item in plan_items
            ],
        )
        store.connection.commit()
    return {"id": plan_id, "query": query.strip(), "read_budget": int(read_budget), "created_at": created_at}


def finish_reading_plan(
    root: Path,
    plan_id: int,
    read: list[str] | None = None,
    verified: list[str] | None = None,
    useful: list[str] | None = None,
    noisy: list[str] | None = None,
    missing: list[str] | None = None,
    summary: str = "",
    source: str = "agent",
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    normalized_source = _source(source)
    event_paths = {
        "read": _paths(read),
        "verified": _paths(verified),
        "useful": _paths(useful),
        "noisy": _paths(noisy),
        "missing": _paths(missing),
    }
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plan_row = store.connection.execute("SELECT * FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if plan_row is None:
            return {"updated": False, "id": plan_id, "plan": None, "events": [], "feedback": [], "suggested_memory": []}
        query = str(plan_row["query"])
    event_records: list[dict[str, Any]] = []
    feedback: list[dict[str, Any]] = []
    for event, paths in event_paths.items():
        for path in paths:
            feedback_id = None
            if event in {"useful", "noisy", "missing"}:
                reason = _feedback_reason(event, path)
                record = add_feedback(root, query, path, event, reason=reason, source=normalized_source)
                feedback_id = int(record["id"])
                feedback.append(record)
            event_records.append({"event": event, "path": path, "feedback_id": feedback_id})
    with GraphStore(root) as store:
        store.initialize()
        events: list[dict[str, Any]] = []
        now = utc_now()
        for record in event_records:
            store.connection.execute(
                """
                INSERT INTO reading_plan_events(plan_id, event, path, note, feedback_id, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (plan_id, record["event"], record["path"], "", record["feedback_id"], now),
            )
            events.append(dict(record))
        store.connection.execute(
            "UPDATE reading_plans SET summary = ?, finished_at = ? WHERE id = ?",
            (summary.strip(), now, plan_id),
        )
        store.connection.commit()
    details = get_reading_plan(root, plan_id)
    return {
        "updated": True,
        "id": plan_id,
        "plan": details,
        "events": events,
        "feedback": feedback,
        "suggested_memory": _suggested_memory_commands(details),
    }


def record_reading_plan_read(
    root: Path,
    plan_id: int,
    paths: list[str],
    note: str = "",
    source: str = "agent",
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    normalized_paths = _paths(paths)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plan_row = store.connection.execute("SELECT * FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if plan_row is None:
            return {"updated": False, "id": plan_id, "plan": None, "events": []}
        now = utc_now()
        events = []
        for path in normalized_paths:
            cursor = store.connection.execute(
                """
                INSERT INTO reading_plan_events(plan_id, event, path, note, feedback_id, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (plan_id, "opened", path, note.strip(), None, now),
            )
            events.append(
                {
                    "id": int(cursor.lastrowid),
                    "plan_id": plan_id,
                    "event": "opened",
                    "path": path,
                    "note": note.strip(),
                    "feedback_id": None,
                    "created_at": now,
                }
            )
        store.connection.commit()
    return {"updated": True, "id": plan_id, "plan": get_reading_plan(root, plan_id), "events": events}


def reading_plan_diff(root: Path, plan_id: int) -> dict[str, Any]:
    plan = get_reading_plan(root, plan_id)
    if plan is None:
        return {"id": plan_id, "found": False, "plan": None, "diff": {}}
    items = list(plan.get("items") or [])
    events = list(plan.get("events") or [])
    planned_paths = [str(item.get("path") or "") for item in items if item.get("path")]
    read_now_paths = [str(item.get("path") or "") for item in items if item.get("read_priority") == "read_now"]
    read_events = _event_paths(events, {"opened", "read"})
    verified_paths = _event_paths(events, {"verified"})
    useful_paths = _event_paths(events, {"useful"})
    noisy_paths = _event_paths(events, {"noisy"})
    missing_paths = _event_paths(events, {"missing"})
    planned_set = set(planned_paths)
    read_set = set(read_events)
    useful_set = set(useful_paths)
    noisy_set = set(noisy_paths)
    missing_set = set(missing_paths)
    return {
        "id": plan_id,
        "found": True,
        "plan": plan,
        "diff": {
            "planned_paths": planned_paths,
            "read_now_paths": read_now_paths,
            "read_paths": read_events,
            "verified_paths": verified_paths,
            "useful_paths": useful_paths,
            "noisy_paths": noisy_paths,
            "missing_paths": missing_paths,
            "suggested_not_read": [path for path in planned_paths if path not in read_set],
            "read_not_planned": [path for path in read_events if path not in planned_set],
            "read_now_not_read": [path for path in read_now_paths if path not in read_set],
            "read_without_outcome": [path for path in read_events if path not in useful_set | noisy_set | missing_set],
        },
    }


def get_reading_plan(root: Path, plan_id: int) -> dict[str, Any] | None:
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plan = store.connection.execute("SELECT * FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if plan is None:
            return None
        items = [
            _item(row)
            for row in store.connection.execute(
                "SELECT * FROM reading_plan_items WHERE plan_id = ? ORDER BY rank, id",
                (plan_id,),
            ).fetchall()
        ]
        events = [
            _event(row)
            for row in store.connection.execute(
                "SELECT * FROM reading_plan_events WHERE plan_id = ? ORDER BY id",
                (plan_id,),
            ).fetchall()
        ]
    return _plan(plan, items, events)


def list_reading_plans(root: Path, limit: int = 20, unfinished_only: bool = False) -> list[dict[str, Any]]:
    bounded = max(1, min(limit, 100))
    where = "WHERE finished_at IS NULL" if unfinished_only else ""
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plans = store.connection.execute(
            f"SELECT * FROM reading_plans {where} ORDER BY id DESC LIMIT ?",
            (bounded,),
        ).fetchall()
        result = []
        for row in plans:
            events = [
                _event(item)
                for item in store.connection.execute(
                    "SELECT * FROM reading_plan_events WHERE plan_id = ? ORDER BY id",
                    (int(row["id"]),),
                ).fetchall()
            ]
            items = [
                _item(item)
                for item in store.connection.execute(
                    "SELECT * FROM reading_plan_items WHERE plan_id = ? ORDER BY rank, id LIMIT 10",
                    (int(row["id"]),),
                ).fetchall()
            ]
            result.append(_plan(row, items, events))
    return result


def reading_plan_stats(root: Path) -> dict[str, Any]:
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plans = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plans").fetchall()]
        items = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plan_items").fetchall()]
        events = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plan_events").fetchall()]
    finished_ids = {int(plan["id"]) for plan in plans if plan.get("finished_at")}
    rank_by_plan_path = {(int(item["plan_id"]), str(item["path"])): int(item["rank"] or 0) for item in items}
    useful_by_rank: Counter[int] = Counter()
    noisy_by_rank: Counter[int] = Counter()
    read_counts: Counter[int] = Counter()
    for event in events:
        plan_id = int(event["plan_id"])
        if str(event["event"]) in {"opened", "read"}:
            read_counts[plan_id] += 1
        rank = rank_by_plan_path.get((plan_id, str(event["path"])), 0)
        if str(event["event"]) == "useful" and rank:
            useful_by_rank[rank] += 1
        if str(event["event"]) == "noisy" and rank:
            noisy_by_rank[rank] += 1
    useful_plan_ranks = [
        (int(event["plan_id"]), rank_by_plan_path.get((int(event["plan_id"]), str(event["path"])), 0))
        for event in events
        if str(event["event"]) == "useful"
    ]
    return {
        "plan_count": len(plans),
        "finished_plan_count": len(finished_ids),
        "unfinished_plan_count": len(plans) - len(finished_ids),
        "average_read_now_count": _average([int(plan["read_budget"] or 0) for plan in plans]),
        "average_files_read_per_finished_plan": _average([read_counts[plan_id] for plan_id in finished_ids]),
        "top1_verified_useful_rate": _rank_rate(useful_plan_ranks, 1, len(finished_ids)),
        "top3_verified_useful_rate": _rank_rate(useful_plan_ranks, 3, len(finished_ids)),
        "useful_hits_by_rank": dict(sorted(useful_by_rank.items())),
        "noisy_hits_by_rank": dict(sorted(noisy_by_rank.items())),
        "missing_count": sum(1 for event in events if str(event["event"]) == "missing"),
    }


def _plan(row: Any, items: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "query": str(row["query"]),
        "query_tokens": json.loads(row["query_tokens_json"] or "[]"),
        "read_budget": int(row["read_budget"] or 0),
        "source": str(row["source"]),
        "summary": str(row["summary"] or ""),
        "finished_at": row["finished_at"],
        "created_at": str(row["created_at"]),
        "items": items,
        "events": events,
    }


def _item(row: Any) -> dict[str, Any]:
    return {
        "path": str(row["path"]),
        "rank": int(row["rank"] or 0),
        "score": float(row["score"] or 0.0),
        "action": str(row["action"] or ""),
        "read_priority": str(row["read_priority"] or ""),
        "read_budget_rank": row["read_budget_rank"],
        "confidence": str(row["confidence"] or ""),
        "sources": json.loads(row["sources_json"] or "[]"),
        "tags": json.loads(row["tags_json"] or "[]"),
        "reason": str(row["reason"] or ""),
    }


def _event(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "plan_id": int(row["plan_id"]),
        "event": str(row["event"]),
        "path": str(row["path"]),
        "note": str(row["note"] or ""),
        "feedback_id": row["feedback_id"],
        "created_at": str(row["created_at"]),
    }


def _source(source: str) -> str:
    normalized = source.lower().strip() or "agent"
    if normalized not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SOURCES))}")
    return normalized


def _paths(values: list[str] | None) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        path = Path(value).as_posix().lstrip("./")
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _feedback_reason(event: str, path: str) -> str:
    if event == "missing":
        return f"verified important file absent from the reading plan: {path}"
    if event == "noisy":
        return f"verified reading-plan candidate was not useful: {path}"
    return f"verified reading-plan candidate was useful: {path}"


def _event_paths(events: list[dict[str, Any]], event_names: set[str]) -> list[str]:
    result = []
    seen = set()
    for event in events:
        if event.get("event") not in event_names:
            continue
        path = str(event.get("path") or "")
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _suggested_memory_commands(plan: dict[str, Any] | None) -> list[dict[str, str]]:
    if not plan:
        return []
    useful = [event["path"] for event in plan.get("events", []) if event.get("event") == "useful"]
    return [
        {
            "path": path,
            "command": f"init-agent tool repo_memory_add --path {path!r} --topic <topic> --evidence read_excerpt --tag <tag> --note <note> --json",
            "reason": "file was marked useful; add memory only if stable behavior was verified",
        }
        for path in useful[:5]
    ]


def _average(values: list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _rank_rate(plan_ranks: list[tuple[int, int]], max_rank: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    matching_plans = {plan_id for plan_id, rank in plan_ranks if 0 < rank <= max_rank}
    return round(len(matching_plans) / denominator, 4)
