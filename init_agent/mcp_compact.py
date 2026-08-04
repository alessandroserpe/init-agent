"""Compact MCP payloads while keeping detailed CLI contracts available."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def compact_mcp_result(result: dict[str, Any]) -> dict[str, Any]:
    tool = str(result.get("tool") or "")
    if tool == "repo_reading_plan":
        return _compact_reading_plan(result)
    if tool == "repo_reading_plan_read":
        return _compact_plan_read(result)
    if tool == "repo_reading_plan_diff":
        return _compact_plan_diff(result)
    if tool == "repo_reading_plan_finish":
        return _compact_plan_finish(result)
    if tool == "repo_reading_plan_mark":
        return _compact_plan_mark(result)
    if tool in {"repo_workstream_report", "repo_workstream_review"}:
        return _compact_workstream_result(result)
    if tool == "repo_flow_topics":
        return _compact_flow_topics(result)
    if tool == "repo_session_summary":
        return _compact_session_summary(result)
    if tool == "repo_session_close":
        return _compact_session_close(result)
    if tool == "repo_related_file":
        return _compact_related_file(result)
    if tool == "repo_symbol_callers":
        return _compact_symbol_callers(result)
    return result


def _base(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in ("tool", "contract", "warnings", "safety")
        if key in result
    }


def _compact_reading_plan(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "id": result.get("id"),
        "query": result.get("query", ""),
        "kind": result.get("kind", "real"),
        "preparation": result.get("preparation", {}),
        "read_budget": result.get("read_budget", 0),
        "query_tokens": list(result.get("query_tokens") or []),
        "plan_items": [_compact_plan_item(item) for item in list(result.get("plan_items") or [])],
        "memory_matches": [_compact_memory(note) for note in list(result.get("memory_matches") or [])[:5]],
        "repo_memory_context": [_compact_memory(note) for note in list(result.get("repo_memory_context") or [])[:3]],
        "recommended_actions": list(result.get("recommended_actions") or [])[:5],
        "delegation": _compact_delegation(result.get("delegation") or {}),
        "compact": True,
    }


def _compact_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": item.get("path", ""),
        "rank": item.get("rank", 0),
        "base_rank": item.get("base_rank", 0),
        "rank_lift": item.get("rank_lift", 0),
        "score": item.get("score", 0.0),
        "action": item.get("action", ""),
        "read_priority": item.get("read_priority", ""),
        "read_budget_rank": item.get("read_budget_rank"),
        "confidence": item.get("confidence", ""),
        "confidence_evidence": list(item.get("confidence_evidence") or [])[:4],
        "signal_rank_lift": dict(item.get("signal_rank_lift") or {}),
        "sources": list(item.get("sources") or []),
        "tags": list(item.get("tags") or [])[:6],
        "memory": [_compact_memory(note) for note in list(item.get("memory") or [])[:1]],
        "feedback": _compact_feedback_signal(item.get("feedback") or {}),
        "trace_path": list(item.get("trace_path") or [])[:6],
        "reason": item.get("reason", ""),
    }


def _compact_memory(note: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "id": note.get("id"),
            "path": note.get("path", ""),
            "scope": note.get("scope", "file"),
            "topic": note.get("topic", ""),
            "note": note.get("note", ""),
            "tags": list(note.get("tags") or [])[:6],
            "evidence": note.get("evidence", "unknown"),
            "stale": note.get("stale"),
            "stale_reason": note.get("stale_reason", ""),
            "score": note.get("score"),
        }.items()
        if value not in (None, "", []) or key in {"id", "stale"}
    }


def _compact_feedback_signal(signal: dict[str, Any]) -> dict[str, Any]:
    if not signal:
        return {}
    return {
        key: signal[key]
        for key in ("net", "boost", "penalty")
        if key in signal
    }


def _compact_plan_read(result: dict[str, Any]) -> dict[str, Any]:
    events = [_compact_event(event) for event in list(result.get("events") or [])]
    return {
        **_base(result),
        "updated": bool(result.get("updated")),
        "id": result.get("id"),
        "plan": _plan_summary(result.get("plan")),
        "event_count": len(events),
        "events": events[:20],
        "events_truncated": len(events) > 20,
        "compact": True,
    }


def _compact_plan_diff(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "id": result.get("id"),
        "found": bool(result.get("found")),
        "plan": _plan_summary(result.get("plan")),
        "diff": result.get("diff", {}),
        "compact": True,
    }


def _compact_plan_finish(result: dict[str, Any]) -> dict[str, Any]:
    events = list(result.get("events") or [])
    outcomes: dict[str, list[str]] = defaultdict(list)
    for event in events:
        name = str(event.get("event") or "")
        path = str(event.get("path") or "")
        if name and path and path not in outcomes[name]:
            outcomes[name].append(path)
    feedback = [
        {
            key: item.get(key)
            for key in ("id", "path", "rating", "reason")
            if item.get(key) not in (None, "")
        }
        for item in list(result.get("feedback") or [])
    ]
    return {
        **_base(result),
        "updated": bool(result.get("updated")),
        "id": result.get("id"),
        "plan": _plan_summary(result.get("plan")),
        "outcomes": dict(outcomes),
        "event_count": len(events),
        "feedback": feedback[:20],
        "suggested_memory": list(result.get("suggested_memory") or [])[:5],
        "blocked_reason": result.get("blocked_reason", ""),
        "pending_review": [
            _compact_workstream(item) for item in list(result.get("pending_review") or [])[:5]
        ],
        "compact": True,
    }


def _compact_plan_mark(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "updated": bool(result.get("updated")),
        "id": result.get("id"),
        "kind": result.get("kind"),
        "plan": _plan_summary(result.get("plan")),
        "compact": True,
    }


def _plan_summary(plan: Any) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    events = list(plan.get("events") or [])
    return {
        "id": plan.get("id"),
        "query": plan.get("query", ""),
        "kind": plan.get("kind", "real"),
        "read_budget": plan.get("read_budget", 0),
        "summary": plan.get("summary", ""),
        "finished_at": plan.get("finished_at"),
        "item_count": len(plan.get("items") or []),
        "event_count": len(events),
        "workstreams": [_compact_workstream(item) for item in list(plan.get("workstreams") or [])[:5]],
    }


def _compact_delegation(delegation: dict[str, Any]) -> dict[str, Any]:
    if not delegation:
        return {}
    return {
        "strategy": delegation.get("strategy", "direct"),
        "recommended": bool(delegation.get("recommended")),
        "reason": delegation.get("reason", ""),
        "task_profile": delegation.get("task_profile", {}),
        "workstreams": [_compact_workstream(item) for item in list(delegation.get("workstreams") or [])[:3]],
        "orchestrator_contract": delegation.get("orchestrator_contract", {}),
        "report_contract": delegation.get("report_contract", {}),
    }


def _compact_workstream(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "key": item.get("key", ""),
            "title": item.get("title", ""),
            "objective": item.get("objective", ""),
            "role": item.get("role", ""),
            "model_tier": item.get("model_tier", ""),
            "reasoning_effort": item.get("reasoning_effort", ""),
            "access_mode": item.get("access_mode", ""),
            "scope_paths": list(item.get("scope_paths") or [])[:5],
            "depends_on": list(item.get("depends_on") or [])[:5],
            "status": item.get("status", ""),
            "agent_name": item.get("agent_name", ""),
            "report": item.get("report", {}),
            "orchestrator_decision": item.get("orchestrator_decision", ""),
            "orchestrator_note": item.get("orchestrator_note", ""),
        }.items()
        if value not in (None, "", [], {}) or key in {"status"}
    }


def _compact_workstream_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "updated": bool(result.get("updated")),
        "id": result.get("id"),
        "workstream_key": result.get("workstream_key", ""),
        "workstream": _compact_workstream(result.get("workstream") or {}),
        "compact": True,
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event.get(key)
        for key in ("id", "event", "path", "note", "feedback_id", "created_at")
        if event.get(key) not in (None, "")
    }


def _compact_flow_topics(result: dict[str, Any]) -> dict[str, Any]:
    flow_data = result.get("flows") or {}
    flows = []
    for flow in list(flow_data.get("flows") or []):
        flows.append(
            {
                "tag": flow.get("tag", ""),
                "file_count": flow.get("file_count", 0),
                "paths": list(flow.get("paths") or [])[:8],
                "paths_truncated": int(flow.get("file_count") or 0) > 8,
                "note_count": flow.get("note_count", 0),
                "stale_count": flow.get("stale_count", 0),
                "file_tag_count": flow.get("file_tag_count", 0),
                "memory_tag_count": flow.get("memory_tag_count", 0),
                "notes": [_compact_memory(note) for note in list(flow.get("notes") or [])[:2]],
                "suggested_flow_memory": flow.get("suggested_flow_memory"),
            }
        )
    return {
        **_base(result),
        "tag": result.get("tag"),
        "flows": {"tag": flow_data.get("tag"), "flows": flows},
        "compact": True,
    }


def _compact_session_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "project": result.get("project", {}),
        "index_health": result.get("index_health", {}),
        "git": result.get("git", {}),
        "recent_memory": [_compact_memory(note) for note in list(result.get("recent_memory") or [])[:3]],
        "recent_feedback": list(result.get("recent_feedback") or [])[:3],
        "recent_tasks": list(result.get("recent_tasks") or [])[:5],
        "plan_activity": _compact_plan_activity(result.get("plan_activity") or {}),
        "memory_audit": result.get("memory_audit", {}),
        "followup_commands": list(result.get("followup_commands") or [])[:5],
        "compact": True,
    }


def _compact_session_close(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **_base(result),
        "project": result.get("project", {}),
        "index_health": result.get("index_health", {}),
        "git": result.get("git", {}),
        "memory_audit": result.get("memory_audit", {}),
        "recent_tasks": list(result.get("recent_tasks") or [])[:5],
        "plan_activity": _compact_plan_activity(result.get("plan_activity") or {}),
        "suggested_feedback": list(result.get("suggested_feedback") or [])[:5],
        "suggested_memory": list(result.get("suggested_memory") or [])[:5],
        "checklist": result.get("checklist", []),
        "close_ready": bool(result.get("close_ready")),
        "followup_commands": list(result.get("followup_commands") or [])[:5],
        "compact": True,
    }


def _compact_related_file(result: dict[str, Any]) -> dict[str, Any]:
    symbols = list(result.get("symbols") or [])
    relations = list(result.get("relations") or [])
    calls = list(result.get("calls") or [])
    callers = list(result.get("called_by") or [])
    commits = list(result.get("recent_commits") or [])
    cochanged = list(result.get("cochanged_files") or [])
    limits = {
        "symbols": 12,
        "relations": 12,
        "calls": 10,
        "called_by": 10,
        "recent_commits": 3,
        "cochanged_files": 8,
    }
    source_counts = dict(result.get("counts") or {})
    return {
        **_base(result),
        "path": result.get("path", ""),
        "preparation": result.get("preparation", {}),
        "file": result.get("file"),
        "symbols": [_compact_symbol(item) for item in symbols[: limits["symbols"]]],
        "relations": [_compact_relation(item) for item in relations[: limits["relations"]]],
        "calls": [_compact_call(item) for item in calls[: limits["calls"]]],
        "called_by": [_compact_caller(item) for item in callers[: limits["called_by"]]],
        "recent_commits": commits[: limits["recent_commits"]],
        "cochanged_files": cochanged[: limits["cochanged_files"]],
        "counts": {
            "symbols": int(source_counts.get("symbols", len(symbols))),
            "relations": int(source_counts.get("relations", len(relations))),
            "calls": int(source_counts.get("calls", len(calls))),
            "called_by": int(source_counts.get("called_by", len(callers))),
            "recent_commits": int(source_counts.get("recent_commits", len(commits))),
            "cochanged_files": int(source_counts.get("cochanged_files", len(cochanged))),
        },
        "truncated": {
            key: int(source_counts.get(key, len(items))) > limits[key]
            for key, items in {
                "symbols": symbols,
                "relations": relations,
                "calls": calls,
                "called_by": callers,
                "recent_commits": commits,
                "cochanged_files": cochanged,
            }.items()
        },
        "followup_commands": list(result.get("followup_commands") or [])[:4],
        "compact": True,
    }


def _compact_symbol_callers(result: dict[str, Any]) -> dict[str, Any]:
    definitions = list(result.get("definitions") or [])
    callers = list(result.get("callers") or [])
    source_counts = dict(result.get("counts") or {})
    definition_count = int(source_counts.get("definitions", len(definitions)))
    caller_count = int(source_counts.get("callers", len(callers)))
    return {
        **_base(result),
        "symbol": result.get("symbol", ""),
        "preparation": result.get("preparation", {}),
        "definitions": [_compact_symbol(item) for item in definitions[:10]],
        "callers": [_compact_caller(item) for item in callers[:15]],
        "counts": {"definitions": definition_count, "callers": caller_count},
        "truncated": {"definitions": definition_count > 10, "callers": caller_count > 15},
        "source_limit_reached": bool(result.get("limit_reached")),
        "followup_commands": list(result.get("followup_commands") or [])[:4],
        "compact": True,
    }


def _compact_symbol(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in ("name", "kind", "line", "end_line", "qualified_name", "container_name", "path", "language")
        if key in item and item[key] not in (None, "")
    }


def _compact_relation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in ("relation", "target_type", "target_id", "confidence")
        if key in item and item[key] not in (None, "")
    }


def _compact_call(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "name": item.get("name", ""),
            "confidence": item.get("confidence"),
            "definitions": [_compact_symbol(definition) for definition in list(item.get("definitions") or [])[:3]],
        }.items()
        if value not in (None, "", [])
    }


def _compact_caller(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "path",
            "language",
            "role",
            "source_symbol",
            "source_qualified_name",
            "call_count",
            "first_line",
            "confidence",
            "commits_together",
        )
        if key in item and item[key] not in (None, "")
    }


def _compact_plan_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_plans": [_plan_summary(plan) for plan in list(activity.get("recent_plans") or [])[:5]],
        "unfinished_plans": [_plan_summary(plan) for plan in list(activity.get("unfinished_plans") or [])[:5]],
        "finished_plan_count": len(activity.get("finished_plans") or []),
        "event_count": activity.get("event_count", 0),
        "read_count": activity.get("read_count", 0),
        "verified_count": activity.get("verified_count", 0),
        "useful_count": activity.get("useful_count", 0),
        "central_count": activity.get("central_count", 0),
        "support_count": activity.get("support_count", 0),
        "created_count": activity.get("created_count", 0),
        "verification_count": activity.get("verification_count", 0),
        "noisy_count": activity.get("noisy_count", 0),
        "missing_count": activity.get("missing_count", 0),
    }
