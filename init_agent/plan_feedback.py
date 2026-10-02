"""Persistent reading-plan tracking and feedback helpers."""

from __future__ import annotations

import json
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .metadata_limits import bounded_metadata
from .graph_store import GraphStore
from .text_tokens import tokenize_query
from .utils import ensure_agent_dir, is_live_repo_file, iter_indexable_files, normalize_repo_path, relative_path, shell_quote, utc_now


MAX_FILE_MANIFEST_BYTES = 8 * 1024 * 1024

SOURCES = {"agent", "user", "benchmark"}
PLAN_KINDS = {"real", "smoke", "experiment", "planning", "diagnostic", "docs"}
EXCLUDED_SCORECARD_KINDS = {"smoke", "experiment", "planning", "diagnostic", "docs"}
WORKSTREAM_DECISIONS = {"accepted", "rework", "rejected"}


@bounded_metadata
def save_reading_plan(
    root: Path,
    query: str,
    plan_items: list[dict[str, Any]],
    read_budget: int,
    source: str = "agent",
    kind: str = "real",
    delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_source = _source(source)
    normalized_kind = _plan_kind(kind)
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        created_at = utc_now()
        file_manifest = _encode_file_manifest(
            [str(row["path"]) for row in store.connection.execute("SELECT path FROM files ORDER BY path")]
        )
        cursor = store.connection.execute(
            """
            INSERT INTO reading_plans(
                query, query_tokens_json, read_budget, source, kind, summary,
                file_manifest_blob, finished_at, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                query.strip(),
                json.dumps(tokenize_query(query), sort_keys=True),
                int(read_budget),
                normalized_source,
                normalized_kind,
                "",
                file_manifest,
                None,
                created_at,
            ),
        )
        plan_id = int(cursor.lastrowid)
        store.connection.executemany(
            """
            INSERT INTO reading_plan_items(
                plan_id, path, rank, score, action, read_priority, read_budget_rank,
                confidence, base_rank, base_score, rank_lift, signal_contributions_json,
                sources_json, tags_json, reason
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(item.get("base_rank") or 0),
                    float(item.get("base_score") or 0.0),
                    int(item.get("rank_lift") or 0),
                    json.dumps(
                        {
                            "scores": dict(item.get("score_components") or {}),
                            "signal_rank_lift": dict(item.get("signal_rank_lift") or {}),
                        },
                        sort_keys=True,
                    ),
                    json.dumps(list(item.get("sources") or []), sort_keys=True),
                    json.dumps(list(item.get("tags") or []), sort_keys=True),
                    str(item.get("reason") or ""),
                )
                for item in plan_items
            ],
        )
        workstreams = list((delegation or {}).get("workstreams") or [])
        store.connection.executemany(
            """
            INSERT INTO reading_plan_workstreams(
                plan_id, workstream_key, title, objective, role, model_tier,
                reasoning_effort, access_mode, scope_paths_json, depends_on_json,
                status, agent_name, report_json, orchestrator_decision,
                orchestrator_note, created_at, updated_at, reviewed_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan_id,
                    str(item.get("key") or f"ws-{index}"),
                    str(item.get("title") or "Delegated workstream"),
                    str(item.get("objective") or ""),
                    str(item.get("role") or "explorer"),
                    str(item.get("model_tier") or "balanced"),
                    str(item.get("reasoning_effort") or "medium"),
                    str(item.get("access_mode") or "read_only"),
                    json.dumps(_paths(item.get("scope_paths") or []), sort_keys=True),
                    json.dumps(_unique([str(value) for value in item.get("depends_on") or []]), sort_keys=True),
                    "proposed",
                    "",
                    "",
                    "",
                    "",
                    created_at,
                    created_at,
                    None,
                )
                for index, item in enumerate(workstreams, start=1)
            ],
        )
        store.connection.commit()
    return {
        "id": plan_id,
        "query": query.strip(),
        "read_budget": int(read_budget),
        "kind": normalized_kind,
        "created_at": created_at,
        "workstream_count": len(workstreams),
    }


@bounded_metadata
def finish_reading_plan(
    root: Path,
    plan_id: int,
    read: list[str] | None = None,
    verified: list[str] | None = None,
    useful: list[str] | None = None,
    central: list[str] | None = None,
    support: list[str] | None = None,
    created: list[str] | None = None,
    verification: list[str] | None = None,
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
    event_paths: dict[str, list[str]] = {
        "read": _paths(read),
        "verified": _paths(verified),
        "useful": _paths(useful),
        "central": _paths(central),
        "support": _paths(support),
        "created": _paths(created),
        "verification": _paths(verification),
        "noisy": _paths(noisy),
        "missing": _paths(missing),
    }
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        plan_row = store.connection.execute("SELECT * FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if plan_row is None:
            return {"updated": False, "id": plan_id, "plan": None, "events": [], "feedback": [], "suggested_memory": []}
        if plan_row["finished_at"]:
            return {"updated": False, "id": plan_id, "already_finished": True, "events": [], "feedback": [], "suggested_memory": []}
        pending_review = [
            _workstream(row)
            for row in store.connection.execute(
                "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? AND status IN ('reported', 'rework') ORDER BY id",
                (plan_id,),
            ).fetchall()
        ]
        if pending_review:
            return {
                "updated": False,
                "id": plan_id,
                "plan": get_reading_plan(root, plan_id),
                "events": [],
                "feedback": [],
                "suggested_memory": [],
                "blocked_reason": "delegated workstreams require orchestrator review or completed rework",
                "pending_review": pending_review,
            }
        query = str(plan_row["query"])
        known_paths = _decode_file_manifest(plan_row["file_manifest_blob"])
    if known_paths is not None:
        current_paths = {
            relative_path(path, root)
            for path in iter_indexable_files(root)
        }
        inferred_created = [
            path
            for path in event_paths["missing"]
            if path not in known_paths and path in current_paths
        ]
        event_paths["missing"] = [path for path in event_paths["missing"] if path not in inferred_created]
        event_paths["created"] = _unique([*event_paths["created"], *inferred_created])
    feedback: list[dict[str, Any]] = []
    with GraphStore(root) as store:
        store.initialize()
        store.connection.execute("BEGIN IMMEDIATE")
        row = store.connection.execute("SELECT finished_at FROM reading_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None or row["finished_at"]:
            return {"updated": False, "id": plan_id, "already_finished": bool(row), "events": [], "feedback": [], "suggested_memory": []}
        events: list[dict[str, Any]] = []
        now = utc_now()
        for event, paths in event_paths.items():
            for path in paths:
                feedback_id = None
                if event in {"useful", "central", "support", "noisy", "missing"}:
                    rating = "crucial" if event == "central" else "useful" if event == "support" else event
                    record = {"query": query, "query_tokens_json": json.dumps(tokenize_query(query)),
                              "path": path, "rating": rating, "reason": _feedback_reason(event, path),
                              "source": normalized_source, "created_at": now}
                    cursor = store.connection.execute("""INSERT INTO orientation_feedback
                        (query, query_tokens_json, path, rating, reason, source, created_at)
                        VALUES (:query, :query_tokens_json, :path, :rating, :reason, :source, :created_at)""", record)
                    feedback_id = int(cursor.lastrowid)
                    record["id"] = feedback_id
                    feedback.append(record)
                store.connection.execute("""INSERT INTO reading_plan_events(plan_id, event, path, note, feedback_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""", (plan_id, event, path, "", feedback_id, now))
                events.append({"event": event, "path": path, "feedback_id": feedback_id})
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
        "suggested_memory": _suggested_memory_commands(root, details),
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


@bounded_metadata
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
    central_paths = _event_paths(events, {"central"})
    support_paths = _event_paths(events, {"support"})
    created_paths = _event_paths(events, {"created"})
    verification_paths = _event_paths(events, {"verification"})
    noisy_paths = _event_paths(events, {"noisy"})
    missing_paths = _event_paths(events, {"missing"})
    planned_set = set(planned_paths)
    read_set = set(read_events)
    useful_set = set([*useful_paths, *central_paths, *support_paths])
    noisy_set = set(noisy_paths)
    missing_set = set(missing_paths)
    workstreams = list(plan.get("workstreams") or [])
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
            "central_paths": central_paths,
            "support_paths": support_paths,
            "created_paths": created_paths,
            "verification_paths": verification_paths,
            "noisy_paths": noisy_paths,
            "missing_paths": missing_paths,
            "suggested_not_read": [path for path in planned_paths if path not in read_set],
            "read_not_planned": [path for path in read_events if path not in planned_set],
            "read_now_not_read": [path for path in read_now_paths if path not in read_set],
            "read_without_outcome": [
                path
                for path in read_events
                if path not in useful_set | noisy_set | missing_set | set(created_paths) | set(verification_paths)
            ],
            "delegation": {
                "proposed": [item["key"] for item in workstreams if item.get("status") == "proposed"],
                "pending_review": [item["key"] for item in workstreams if item.get("status") == "reported"],
                "accepted": [item["key"] for item in workstreams if item.get("status") == "accepted"],
                "rework": [item["key"] for item in workstreams if item.get("status") == "rework"],
                "rejected": [item["key"] for item in workstreams if item.get("status") == "rejected"],
            },
        },
    }


@bounded_metadata
def record_workstream_report(
    root: Path,
    plan_id: int,
    workstream_key: str,
    agent_name: str,
    summary: str,
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
    tests: list[str] | None = None,
    findings: list[str] | None = None,
    risks: list[str] | None = None,
    remaining: list[str] | None = None,
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    key = workstream_key.strip()
    if not key:
        raise ValueError("workstream key is required")
    if not summary.strip():
        raise ValueError("workstream report summary is required")
    report = {
        "summary": summary.strip(),
        "files_read": _paths(files_read),
        "files_modified": _paths(files_modified),
        "tests": _strings(tests),
        "findings": _strings(findings),
        "risks": _strings(risks),
        "remaining": _strings(remaining),
    }
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = store.connection.execute(
            "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? AND workstream_key = ?",
            (plan_id, key),
        ).fetchone()
        if row is None:
            return {"updated": False, "id": plan_id, "workstream_key": key, "workstream": None}
        if str(row["status"] or "") in {"accepted", "rejected"}:
            raise ValueError("reviewed workstream reports cannot be replaced")
        now = utc_now()
        store.connection.execute(
            """
            UPDATE reading_plan_workstreams
            SET status = 'reported', agent_name = ?, report_json = ?,
                orchestrator_decision = '', orchestrator_note = '',
                reviewed_at = NULL, updated_at = ?
            WHERE plan_id = ? AND workstream_key = ?
            """,
            (agent_name.strip() or "subagent", json.dumps(report, sort_keys=True), now, plan_id, key),
        )
        store.connection.executemany(
            """
            INSERT INTO reading_plan_events(plan_id, event, path, note, feedback_id, created_at)
            VALUES(?, 'opened', ?, ?, NULL, ?)
            """,
            [
                (
                    plan_id,
                    path,
                    f"delegated workstream {key} reported by {agent_name.strip() or 'subagent'}",
                    now,
                )
                for path in report["files_read"]
            ],
        )
        store.connection.commit()
        updated = store.connection.execute(
            "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? AND workstream_key = ?",
            (plan_id, key),
        ).fetchone()
    return {"updated": True, "id": plan_id, "workstream_key": key, "workstream": _workstream(updated)}


@bounded_metadata
def review_workstream_report(
    root: Path,
    plan_id: int,
    workstream_key: str,
    decision: str,
    note: str = "",
) -> dict[str, Any]:
    if plan_id <= 0:
        raise ValueError("plan id must be positive")
    key = workstream_key.strip()
    normalized_decision = decision.lower().strip()
    if not key:
        raise ValueError("workstream key is required")
    if normalized_decision not in WORKSTREAM_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(WORKSTREAM_DECISIONS))}")
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        row = store.connection.execute(
            "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? AND workstream_key = ?",
            (plan_id, key),
        ).fetchone()
        if row is None:
            return {"updated": False, "id": plan_id, "workstream_key": key, "workstream": None}
        if not str(row["report_json"] or "").strip():
            raise ValueError("the workstream has no report to review")
        now = utc_now()
        store.connection.execute(
            """
            UPDATE reading_plan_workstreams
            SET status = ?, orchestrator_decision = ?, orchestrator_note = ?,
                reviewed_at = ?, updated_at = ?
            WHERE plan_id = ? AND workstream_key = ?
            """,
            (normalized_decision, normalized_decision, note.strip(), now, now, plan_id, key),
        )
        store.connection.commit()
        updated = store.connection.execute(
            "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? AND workstream_key = ?",
            (plan_id, key),
        ).fetchone()
    return {"updated": True, "id": plan_id, "workstream_key": key, "workstream": _workstream(updated)}


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
                "SELECT * FROM reading_plan_items WHERE plan_id = ? ORDER BY rank, id LIMIT 129",
                (plan_id,),
            ).fetchall()
        ]
        events = [
            _event(row)
            for row in store.connection.execute(
                "SELECT * FROM reading_plan_events WHERE plan_id = ? ORDER BY id LIMIT 1001",
                (plan_id,),
            ).fetchall()
        ]
        workstreams = [
            _workstream(row)
            for row in store.connection.execute(
                "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? ORDER BY id LIMIT 1001",
                (plan_id,),
            ).fetchall()
        ]
    return _plan(plan, items, events, workstreams)


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
                    "SELECT * FROM reading_plan_events WHERE plan_id = ? ORDER BY id LIMIT 1001",
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
            workstreams = [
                _workstream(item)
                for item in store.connection.execute(
                    "SELECT * FROM reading_plan_workstreams WHERE plan_id = ? ORDER BY id LIMIT 1001",
                    (int(row["id"]),),
                ).fetchall()
            ]
            result.append(_plan(row, items, events, workstreams))
    return result


def reading_plan_stats(root: Path, limit: int = 20, include_all: bool = False) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 100))
    ensure_agent_dir(root)
    with GraphStore(root) as store:
        store.initialize()
        counts = store.connection.execute("SELECT COUNT(*) AS total, COUNT(finished_at) AS finished FROM reading_plans").fetchone()
        plans = [dict(row) for row in store.connection.execute(
            "SELECT * FROM reading_plans WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT ?", (bounded_limit,))]
        ids = [int(row["id"]) for row in plans]
        placeholders = ",".join("?" for _ in ids) or "NULL"
        items = [dict(row) for row in store.connection.execute(
            f"SELECT * FROM reading_plan_items WHERE plan_id IN ({placeholders}) ORDER BY id LIMIT 10001", ids)]
        events = [dict(row) for row in store.connection.execute(
            f"SELECT * FROM reading_plan_events WHERE plan_id IN ({placeholders}) ORDER BY id LIMIT 10001", ids)]
        history_truncated = len(items) > 10000 or len(events) > 10000
        items, events = items[:10000], events[:10000]
    for plan in plans:
        plan["effective_kind"] = _effective_plan_kind(plan)
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
    rank_by_plan_path = {(int(item["plan_id"]), str(item["path"])): int(item["rank"] or 0) for item in items}
    item_by_plan_path = {(int(item["plan_id"]), str(item["path"])): item for item in items}
    planned_paths = defaultdict(set)
    for item in items:
        planned_paths[int(item["plan_id"])].add(str(item["path"]))
    useful_by_rank: Counter[int] = Counter()
    noisy_by_rank: Counter[int] = Counter()
    event_paths: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for event in events:
        plan_id = int(event["plan_id"])
        event_name = str(event["event"])
        path = str(event["path"])
        if plan_id in finished_ids and path:
            event_paths[plan_id][event_name].append(path)
        rank = rank_by_plan_path.get((plan_id, str(event["path"])), 0)
        if plan_id in finished_ids and event_name in {"useful", "central"} and rank:
            useful_by_rank[rank] += 1
        if plan_id in finished_ids and event_name == "noisy" and rank:
            noisy_by_rank[rank] += 1
    plan_rows = []
    evaluable_ids = set()
    first_useful_positions: list[int] = []
    missing_rates: list[float] = []
    noise_rates: list[float] = []
    outcome_coverages: list[float] = []
    verified_coverages: list[float] = []
    base_rank_lifts: list[int] = []
    signal_lifts: dict[str, list[int]] = defaultdict(list)
    signal_observations: Counter[str] = Counter()
    explicitly_tracked_plans = 0
    for plan in included_plans:
        plan_id = int(plan["id"])
        paths_by_event = event_paths.get(plan_id, {})
        useful = _unique(paths_by_event.get("useful", []))
        central = _unique(paths_by_event.get("central", []))
        support = _unique(paths_by_event.get("support", []))
        created = _unique(paths_by_event.get("created", []))
        verification = _unique(paths_by_event.get("verification", []))
        missing = _unique(paths_by_event.get("missing", []))
        noisy = _unique(paths_by_event.get("noisy", []))
        opened = _unique(paths_by_event.get("opened", []))
        verified = _unique(paths_by_event.get("verified", []))
        read = _unique([*paths_by_event.get("opened", []), *paths_by_event.get("read", [])])
        expected = _unique([*(central or useful), *missing])
        is_evaluable = bool(expected or noisy)
        if is_evaluable:
            evaluable_ids.add(plan_id)
        first_position = _first_matching_position(read, expected)
        orientation_read = read[:first_position] if first_position else read
        extra_read_count = len([path for path in orientation_read if path not in planned_paths.get(plan_id, set())])
        if first_position:
            first_useful_positions.append(first_position)
        if expected:
            missing_rates.append(round(len(missing) / len(expected), 4))
        if planned_paths.get(plan_id):
            noise_rates.append(round(len(noisy) / len(planned_paths[plan_id]), 4))
        if opened:
            explicitly_tracked_plans += 1
        classified = set([*useful, *central, *support, *created, *verification, *noisy, *missing])
        outcome_coverage = round(len(set(read).intersection(classified)) / len(read), 4) if read else None
        verified_coverage = round(len(set(read).intersection(verified)) / len(read), 4) if read else None
        if outcome_coverage is not None:
            outcome_coverages.append(outcome_coverage)
        if verified_coverage is not None:
            verified_coverages.append(verified_coverage)
        for path in central or useful:
            item = item_by_plan_path.get((plan_id, path))
            if not item:
                continue
            base_rank = int(item.get("base_rank") or 0)
            rank = int(item.get("rank") or 0)
            if base_rank and rank:
                base_rank_lifts.append(base_rank - rank)
            try:
                contributions = json.loads(item.get("signal_contributions_json") or "{}")
            except json.JSONDecodeError:
                contributions = {}
            scores = dict(contributions.get("scores") or {})
            lifts = dict(contributions.get("signal_rank_lift") or {})
            for signal in ("memory", "feedback", "tags"):
                lift = int(lifts.get(signal) or 0)
                if abs(float(scores.get(signal) or 0.0)) > 0.0 or lift != 0:
                    signal_observations[signal] += 1
                    signal_lifts[signal].append(lift)
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
                "orientation_read_count": len(orientation_read),
                "extra_read_count": extra_read_count,
                "useful_count": len(useful),
                "central_count": len(central),
                "support_count": len(support),
                "created_count": len(created),
                "verification_count": len(verification),
                "missing_count": len(missing),
                "noisy_count": len(noisy),
                "explicit_read_tracking": bool(opened),
                "read_outcome_coverage": outcome_coverage,
                "verified_read_coverage": verified_coverage,
                "summary": str(plan.get("summary") or ""),
            }
        )
    excluded_by_kind = Counter(str(plan.get("effective_kind") or "real") for plan in excluded_plans)
    evaluable_count = len(evaluable_ids)
    explicit_tracking_rate = round(explicitly_tracked_plans / len(included_plans), 4) if included_plans else 0.0
    outcome_coverage = _float_average(outcome_coverages)
    confidence, confidence_reasons = scorecard_evidence_confidence(
        evaluable_count,
        explicit_tracking_rate,
        outcome_coverage,
    )
    signal_impact = {
        signal: {
            "observed_useful_files": int(signal_observations[signal]),
            "average_rank_lift": _average(signal_lifts.get(signal, [])),
            "promoted": sum(1 for value in signal_lifts.get(signal, []) if value > 0),
            "unchanged": sum(1 for value in signal_lifts.get(signal, []) if value == 0),
            "demoted": sum(1 for value in signal_lifts.get(signal, []) if value < 0),
        }
        for signal in ("memory", "feedback", "tags")
    }
    return {
        "plan_count": int(counts["total"]),
        "finished_plan_count": int(counts["finished"]),
        "unfinished_plan_count": int(counts["total"]) - int(counts["finished"]),
        "history_truncated": history_truncated,
        "scorecard_limit": bounded_limit,
        "scorecard_include_all": bool(include_all),
        "scorecard_included_plan_count": len(included_plans),
        "scorecard_excluded_plan_count": len(excluded_plans),
        "scorecard_excluded_by_kind": dict(sorted(excluded_by_kind.items())),
        "scorecard_evaluable_plan_count": evaluable_count,
        "scorecard_not_evaluable_plan_count": len(included_plans) - evaluable_count,
        "average_read_now_count": _average([int(plan["read_budget"] or 0) for plan in included_plans]),
        "average_files_read_per_finished_plan": _average([int(plan["read_file_count"]) for plan in plan_rows]),
        "average_extra_files_read_per_finished_plan": _average([int(plan["extra_read_count"]) for plan in plan_rows]),
        "average_first_useful_read_position": _average(first_useful_positions),
        "average_base_to_assisted_rank_lift": _average(base_rank_lifts),
        "signal_impact": signal_impact,
        "explicit_read_tracking_rate": explicit_tracking_rate,
        "average_read_outcome_coverage": outcome_coverage,
        "average_verified_read_coverage": _float_average(verified_coverages),
        "scorecard_confidence": confidence,
        "scorecard_confidence_reasons": confidence_reasons,
        "missing_rate": _float_average(missing_rates),
        "noise_rate": _float_average(noise_rates),
        "top1_verified_useful_rate": _plan_boolean_rate(plan_rows, "top1_hit"),
        "top3_verified_useful_rate": _plan_boolean_rate(plan_rows, "top3_hit"),
        "top1_hit_rate": _plan_boolean_rate([plan for plan in plan_rows if plan["evaluable"]], "top1_hit"),
        "top3_hit_rate": _plan_boolean_rate([plan for plan in plan_rows if plan["evaluable"]], "top3_hit"),
        "top5_hit_rate": _plan_boolean_rate([plan for plan in plan_rows if plan["evaluable"]], "top5_hit"),
        "useful_hits_by_rank": dict(sorted(useful_by_rank.items())),
        "noisy_hits_by_rank": dict(sorted(noisy_by_rank.items())),
        "missing_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "missing"),
        "noisy_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "noisy"),
        "useful_count": sum(
            1
            for event in events
            if int(event["plan_id"]) in finished_ids and str(event["event"]) in {"useful", "central", "support"}
        ),
        "central_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "central"),
        "support_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "support"),
        "created_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "created"),
        "verification_count": sum(1 for event in events if int(event["plan_id"]) in finished_ids and str(event["event"]) == "verification"),
        "plans": plan_rows,
    }


def scorecard_evidence_confidence(evaluable_count: int, explicit_tracking_rate: float, outcome_coverage: float) -> tuple[str, list[str]]:
    reasons = [f"{evaluable_count} evaluable real plans"]
    reasons.append(f"{explicit_tracking_rate * 100:.0f}% used explicit plan-read tracking")
    reasons.append(f"{outcome_coverage * 100:.0f}% of read files received classified outcomes")
    if evaluable_count >= 20 and explicit_tracking_rate >= 0.8 and outcome_coverage >= 0.6:
        return "high", reasons
    if evaluable_count >= 5 and explicit_tracking_rate >= 0.5 and outcome_coverage >= 0.4:
        return "medium", reasons
    return "low", reasons


def _plan(
    row: Any,
    items: list[dict[str, Any]],
    events: list[dict[str, Any]],
    workstreams: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        "items": items[:128],
        "events": events[:1000],
        "history_truncated": len(items) > 128 or len(events) > 1000 or len(workstreams or []) > 1000,
        "workstreams": (workstreams or [])[:1000],
    }


def _item(row: Any) -> dict[str, Any]:
    contributions = json.loads(row["signal_contributions_json"] or "{}")
    return {
        "path": str(row["path"]),
        "rank": int(row["rank"] or 0),
        "score": float(row["score"] or 0.0),
        "action": str(row["action"] or ""),
        "read_priority": str(row["read_priority"] or ""),
        "read_budget_rank": row["read_budget_rank"],
        "confidence": str(row["confidence"] or ""),
        "base_rank": int(row["base_rank"] or 0),
        "base_score": float(row["base_score"] or 0.0),
        "rank_lift": int(row["rank_lift"] or 0),
        "score_components": dict(contributions.get("scores") or {}),
        "signal_rank_lift": dict(contributions.get("signal_rank_lift") or {}),
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


def _workstream(row: Any) -> dict[str, Any]:
    report = json.loads(row["report_json"] or "{}")
    return {
        "id": int(row["id"]),
        "plan_id": int(row["plan_id"]),
        "key": str(row["workstream_key"]),
        "title": str(row["title"]),
        "objective": str(row["objective"]),
        "role": str(row["role"]),
        "model_tier": str(row["model_tier"]),
        "reasoning_effort": str(row["reasoning_effort"]),
        "access_mode": str(row["access_mode"]),
        "scope_paths": json.loads(row["scope_paths_json"] or "[]"),
        "depends_on": json.loads(row["depends_on_json"] or "[]"),
        "status": str(row["status"]),
        "agent_name": str(row["agent_name"] or ""),
        "report": report,
        "orchestrator_decision": str(row["orchestrator_decision"] or ""),
        "orchestrator_note": str(row["orchestrator_note"] or ""),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "reviewed_at": row["reviewed_at"],
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
        path = normalize_repo_path(value)
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _strings(values: list[str] | None) -> list[str]:
    return _unique([str(value).strip() for value in values or [] if str(value).strip()])


def _feedback_reason(event: str, path: str) -> str:
    if event == "missing":
        return f"verified important file absent from the reading plan: {path}"
    if event == "noisy":
        return f"verified reading-plan candidate was not useful: {path}"
    if event == "central":
        return f"verified central orientation target for the reading plan: {path}"
    if event == "support":
        return f"verified supporting file after the central area was found: {path}"
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


def _suggested_memory_commands(root: Path, plan: dict[str, Any] | None) -> list[dict[str, str]]:
    if not plan:
        return []
    useful = [
        event["path"]
        for event in plan.get("events", [])
        if event.get("event") in {"central", "useful"}
        and is_live_repo_file(root, event.get("path"))
    ]
    return [
        {
            "path": path,
            "command": f"init-agent tool repo_memory_add --path {shell_quote(path)} --topic <topic> --evidence read_excerpt --tag <tag> --note <note> --json",
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


def _plan_boolean_rate(plans: list[dict[str, Any]], key: str) -> float:
    if not plans:
        return 0.0
    return round(sum(1 for plan in plans if plan.get(key)) / len(plans), 4)


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


def _encode_file_manifest(paths: list[str]) -> bytes:
    payload = json.dumps(sorted(set(paths)), separators=(",", ":")).encode("utf-8")
    return zlib.compress(payload, level=9)


def _decode_file_manifest(value: Any) -> set[str] | None:
    if not isinstance(value, (bytes, bytearray, memoryview, str)):
        return None
    if not value or len(value) > MAX_FILE_MANIFEST_BYTES:
        return None
    try:
        raw = bytes(value) if not isinstance(value, str) else value.encode("latin-1")
        if len(raw) > MAX_FILE_MANIFEST_BYTES:
            return None
        # Bound output before allocating/parsing data from the untrusted index.
        decompressor = zlib.decompressobj()
        payload = decompressor.decompress(raw, MAX_FILE_MANIFEST_BYTES + 1)
        if len(payload) > MAX_FILE_MANIFEST_BYTES or not decompressor.eof or decompressor.unused_data:
            return None
        decoded = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, zlib.error, RecursionError):
        return None
    if not isinstance(decoded, list) or not all(isinstance(path, str) for path in decoded):
        return None
    return set(decoded)
