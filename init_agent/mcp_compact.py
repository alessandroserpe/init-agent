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
    if tool == "repo_flow_topics":
        return _compact_flow_topics(result)
    if tool == "repo_session_summary":
        return _compact_session_summary(result)
    if tool == "repo_session_close":
        return _compact_session_close(result)
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
        "compact": True,
    }


def _compact_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": item.get("path", ""),
        "rank": item.get("rank", 0),
        "score": item.get("score", 0.0),
        "action": item.get("action", ""),
        "read_priority": item.get("read_priority", ""),
        "read_budget_rank": item.get("read_budget_rank"),
        "confidence": item.get("confidence", ""),
        "confidence_evidence": list(item.get("confidence_evidence") or [])[:4],
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


def _compact_plan_activity(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "recent_plans": [_plan_summary(plan) for plan in list(activity.get("recent_plans") or [])[:5]],
        "unfinished_plans": [_plan_summary(plan) for plan in list(activity.get("unfinished_plans") or [])[:5]],
        "finished_plan_count": len(activity.get("finished_plans") or []),
        "event_count": activity.get("event_count", 0),
        "read_count": activity.get("read_count", 0),
        "verified_count": activity.get("verified_count", 0),
        "useful_count": activity.get("useful_count", 0),
        "noisy_count": activity.get("noisy_count", 0),
        "missing_count": activity.get("missing_count", 0),
    }
