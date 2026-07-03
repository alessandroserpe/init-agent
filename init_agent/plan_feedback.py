"""Persistent reading-plan tracking and feedback helpers."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .feedback import add_feedback
from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import ensure_agent_dir, utc_now


SOURCES = {"agent", "user", "benchmark"}
PLAN_KINDS = {"real", "smoke", "experiment", "planning", "diagnostic", "docs"}
EXCLUDED_SCORECARD_KINDS = {"smoke", "experiment", "planning", "diagnostic", "docs"}


def save_reading_plan(
    root: Path,
    query: str,
    plan_items: list[dict[str, Any]],
    read_budget: int,
    source: str = "agent",
    kind: str = "real",
) -> dict[str, Any]:
    normalized_source = _source(source)
    normalized_kind = _plan_kind(kind)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        created_at = utc_now()
        cursor = store.connection.execute(
            """
            INSERT INTO reading_plans(query, query_tokens_json, read_budget, source, kind, summary, finished_at, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query.strip(),
                json.dumps(tokenize_query(query), sort_keys=True),
                int(read_budget),
                normalized_source,
                normalized_kind,
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
    return {
        "id": plan_id,
        "query": query.strip(),
        "read_budget": int(read_budget),
        "kind": normalized_kind,
        "created_at": created_at,
    }


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
    kind: str | None = None,
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    normalized_source = _source(source)
    normalized_kind = _plan_kind(kind) if kind is not None else None
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
        if normalized_kind is None:
            store.connection.execute(
                "UPDATE reading_plans SET summary = ?, finished_at = ? WHERE id = ?",
                (summary.strip(), now, plan_id),
            )
        else:
            store.connection.execute(
                "UPDATE reading_plans SET summary = ?, finished_at = ?, kind = ? WHERE id = ?",
                (summary.strip(), now, normalized_kind, plan_id),
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


def mark_reading_plan_kind(root: Path, plan_id: int, kind: str) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    normalized_kind = _plan_kind(kind)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = store.connection.execute("SELECT * FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            return {"updated": False, "id": plan_id, "plan": None}
        store.connection.execute("UPDATE reading_plans SET kind = ? WHERE id = ?", (normalized_kind, plan_id))
        store.connection.commit()
    return {"updated": True, "id": plan_id, "kind": normalized_kind, "plan": get_reading_plan(root, plan_id)}


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


def reading_plan_stats(root: Path, limit: int = 20, include_all: bool = False) -> dict[str, Any]:
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plans = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plans").fetchall()]
        items = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plan_items").fetchall()]
        events = [dict(row) for row in store.connection.execute("SELECT * FROM reading_plan_events").fetchall()]
    for plan in plans:
        plan["effective_kind"] = _effective_plan_kind(plan)
    bounded_limit = max(1, min(int(limit), 100))
    finished_plans = [plan for plan in plans if plan.get("finished_at")]
    finished_plans.sort(key=lambda item: int(item["id"]), reverse=True)
    recent_finished = finished_plans[:bounded_limit]
    included_plans = [
        plan
        for plan in recent_finished
        if include_all or str(plan.get("effective_kind") or "real") not in EXCLUDED_SCORECARD_KINDS
    ]
    excluded_plans = [plan for plan in recent_finished if plan not in included_plans]
    finished_ids = {int(plan["id"]) for plan in included_plans}
    all_finished_ids = {int(plan["id"]) for plan in finished_plans}
    rank_by_plan_path = {(int(item["plan_id"]), str(item["path"])): int(item["rank"] or 0) for item in items}
    planned_paths = defaultdict(set)
    for item in items:
        planned_paths[int(item["plan_id"])].add(str(item["path"]))
    useful_by_rank: Counter[int] = Counter()
    noisy_by_rank: Counter[int] = Counter()
    read_counts: Counter[int] = Counter()
    event_paths: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for event in events:
        plan_id = int(event["plan_id"])
        event_name = str(event["event"])
        path = str(event["path"])
        if event_name in {"opened", "read"}:
            read_counts[plan_id] += 1
        if plan_id in finished_ids and path:
            event_paths[plan_id][event_name].append(path)
        rank = rank_by_plan_path.get((plan_id, str(event["path"])), 0)
        if plan_id in finished_ids and event_name == "useful" and rank:
            useful_by_rank[rank] += 1
        if plan_id in finished_ids and event_name == "noisy" and rank:
            noisy_by_rank[rank] += 1
    useful_plan_ranks = [
        (int(event["plan_id"]), rank_by_plan_path.get((int(event["plan_id"]), str(event["path"])), 0))
        for event in events
        if int(event["plan_id"]) in finished_ids and str(event["event"]) == "useful"
    ]
    expected_plan_ranks = [
        (int(event["plan_id"]), rank_by_plan_path.get((int(event["plan_id"]), str(event["path"])), 0))
        for event in events
        if int(event["plan_id"]) in finished_ids and str(event["event"]) in {"useful", "missing"}
    ]
    plan_rows = []
    evaluable_ids = set()
    first_useful_positions: list[int] = []
    missing_rates: list[float] = []
    noise_rates: list[float] = []
    for plan in included_plans:
        plan_id = int(plan["id"])
        paths_by_event = event_paths.get(plan_id, {})
        useful = _unique(paths_by_event.get("useful", []))
        missing = _unique(paths_by_event.get("missing", []))
        noisy = _unique(paths_by_event.get("noisy", []))
        read = _unique([*paths_by_event.get("opened", []), *paths_by_event.get("read", [])])
        extra_read_count = len([path for path in read if path not in planned_paths.get(plan_id, set())])
        expected = _unique([*useful, *missing])
        is_evaluable = bool(expected or noisy)
        if is_evaluable:
            evaluable_ids.add(plan_id)
        first_position = _first_matching_position(read, expected)
        if first_position:
            first_useful_positions.append(first_position)
        if expected:
            missing_rates.append(round(len(missing) / len(expected), 4))
        if planned_paths.get(plan_id):
            noise_rates.append(round(len(noisy) / len(planned_paths[plan_id]), 4))
        plan_rows.append(
            {
                "id": plan_id,
                "query": str(plan["query"]),
                "kind": str(plan.get("effective_kind") or "real"),
                "evaluable": is_evaluable,
                "top1_hit": _has_rank_hit(expected, rank_by_plan_path, plan_id, 1),
                "top3_hit": _has_rank_hit(expected, rank_by_plan_path, plan_id, 3),
                "top5_hit": _has_rank_hit(expected, rank_by_plan_path, plan_id, 5),
                "first_useful_read_position": first_position,
                "planned_file_count": len(planned_paths.get(plan_id, set())),
                "read_file_count": len(read),
                "extra_read_count": extra_read_count,
                "useful_count": len(useful),
                "missing_count": len(missing),
                "noisy_count": len(noisy),
                "summary": str(plan.get("summary") or ""),
            }
        )
    excluded_by_kind = Counter(str(plan.get("effective_kind") or "real") for plan in excluded_plans)
    evaluable_count = len(evaluable_ids)
    return {
        "plan_count": len(plans),
        "finished_plan_count": len(all_finished_ids),
        "unfinished_plan_count": len(plans) - len(all_finished_ids),
        "scorecard_limit": bounded_limit,
        "scorecard_include_all": bool(include_all),
        "scorecard_included_plan_count": len(included_plans),
        "scorecard_excluded_plan_count": len(excluded_plans),
        "scorecard_excluded_by_kind": dict(sorted(excluded_by_kind.items())),
        "scorecard_evaluable_plan_count": evaluable_count,
        "scorecard_not_evaluable_plan_count": len(included_plans) - evaluable_count,
        "average_read_now_count": _average([int(plan["read_budget"] or 0) for plan in plans]),
        "average_files_read_per_finished_plan": _average([read_counts[plan_id] for plan_id in finished_ids]),
        "average_extra_files_read_per_finished_plan": _average([int(plan["extra_read_count"]) for plan in plan_rows]),
        "average_first_useful_read_position": _average(first_useful_positions),
        "missing_rate": _float_average(missing_rates),
        "noise_rate": _float_average(noise_rates),
        "top1_verified_useful_rate": _rank_rate(useful_plan_ranks, 1, max(1, len(finished_ids))),
        "top3_verified_useful_rate": _rank_rate(useful_plan_ranks, 3, max(1, len(finished_ids))),
        "top1_hit_rate": _rank_rate(expected_plan_ranks, 1, evaluable_count),
        "top3_hit_rate": _rank_rate(expected_plan_ranks, 3, evaluable_count),
        "top5_hit_rate": _rank_rate(expected_plan_ranks, 5, evaluable_count),
        "useful_hits_by_rank": dict(sorted(useful_by_rank.items())),
        "noisy_hits_by_rank": dict(sorted(noisy_by_rank.items())),
        "missing_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "missing"),
        "noisy_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "noisy"),
        "plans": plan_rows,
    }


def _plan(row: Any, items: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "query": str(row["query"]),
        "query_tokens": json.loads(row["query_tokens_json"] or "[]"),
        "read_budget": int(row["read_budget"] or 0),
        "source": str(row["source"]),
        "kind": _effective_plan_kind(dict(row)),
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


def _plan_kind(kind: str | None) -> str:
    normalized = (kind or "real").lower().strip().replace("_", "-")
    aliases = {"test": "smoke", "smoketest": "smoke", "doc": "docs", "documentation": "docs"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in PLAN_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(sorted(PLAN_KINDS))}")
    return normalized


def _effective_plan_kind(plan: dict[str, Any]) -> str:
    explicit = str(plan.get("kind") or "").strip()
    if explicit:
        return _plan_kind(explicit)
    text = f"{plan.get('query') or ''} {plan.get('summary') or ''}".lower()
    if any(token in text for token in ("smoke", "smoke check", "upgrade")):
        return "smoke"
    if any(token in text for token in ("experiment", "esperimento", "prototype", "probe")):
        return "experiment"
    if any(token in text for token in ("roadmap", "priorità", "priority", "planning")):
        return "planning"
    if any(token in text for token in ("diagnostic", "diagnost", "exploratory", "debug ranking")):
        return "diagnostic"
    if any(token in text for token in ("document", "docs", "readme")) and "modific" not in text:
        return "docs"
    return "real"


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


def _float_average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _rank_rate(plan_ranks: list[tuple[int, int]], max_rank: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    matching_plans = {plan_id for plan_id, rank in plan_ranks if 0 < rank <= max_rank}
    return round(len(matching_plans) / denominator, 4)


def _unique(paths: list[str]) -> list[str]:
    result = []
    seen = set()
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _first_matching_position(read_paths: list[str], expected_paths: list[str]) -> int | None:
    expected = set(expected_paths)
    if not expected:
        return None
    for index, path in enumerate(read_paths, start=1):
        if path in expected:
            return index
    return None


def _has_rank_hit(paths: list[str], ranks: dict[tuple[int, str], int], plan_id: int, max_rank: int) -> bool:
    return any(0 < ranks.get((plan_id, path), 0) <= max_rank for path in paths)
