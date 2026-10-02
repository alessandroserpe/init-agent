"""MCP tool schemas and handlers for init-agent."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .metadata_limits import bounded_metadata, validate_input, MAX_ITEMS, MAX_STRING
from .mcp_compact import compact_mcp_result

from .agent_tools import (
    repo_entrypoints,
    repo_feedback_add,
    repo_feedback_explain,
    repo_file_notes,
    repo_flow_topics,
    repo_graph_search,
    repo_memory_add,
    repo_memory_audit,
    repo_memory_delete,
    repo_memory_list,
    repo_memory_search,
    repo_memory_topics,
    repo_memory_update,
    repo_overview,
    repo_reading_plan,
    repo_reading_plan_diff,
    repo_reading_plan_finish,
    repo_reading_plan_mark,
    repo_reading_plan_read,
    repo_reading_plan_stats,
    repo_related_file,
    repo_session_close,
    repo_session_summary,
    repo_symbol_callers,
    repo_task_add,
    repo_task_close,
    repo_task_list,
    repo_task_note,
    repo_task_update,
    repo_trace,
    repo_workstream_report,
    repo_workstream_review,
)


ToolHandler = Callable[[Path, dict[str, Any]], dict[str, Any]]


MCP_CORE_TOOL_NAMES = frozenset(
    {
        "repo_overview",
        "repo_reading_plan",
        "repo_reading_plan_finish",
        "repo_related_file",
        "repo_symbol_callers",
        "repo_memory_search",
        "repo_memory_add",
        "repo_session_close",
    }
)
MCP_TOOL_PROFILES = ("core", "full")


def _handle_repo_graph_search(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_graph_search requires query")
    limit = int(arguments.get("limit") or 10)
    return repo_graph_search(root, query, limit=limit, prepare=False)


def _handle_repo_trace(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_trace requires query")
    limit = int(arguments.get("limit") or 10)
    max_depth = int(arguments.get("max_depth") or 4)
    return repo_trace(root, query, limit=limit, max_depth=max_depth, prepare=False)


def _handle_repo_reading_plan(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_reading_plan requires query")
    limit = int(arguments.get("limit") or 10)
    read_budget = int(arguments.get("read_budget") or arguments.get("read") or 3)
    kind = str(arguments.get("kind") or "real")
    delegate = bool(arguments.get("delegate") or False)
    return _mcp_result(
        arguments,
        repo_reading_plan(
            root,
            query,
            limit=limit,
            read_budget=read_budget,
            prepare=False,
            kind=kind,
            delegate=delegate,
        ),
    )


def _handle_repo_reading_plan_read(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    if plan_id <= 0:
        raise ValueError("repo_reading_plan_read requires positive id")
    paths = _string_list(arguments.get("paths"))
    if not paths:
        paths = _string_list(arguments.get("path"))
    if not paths:
        raise ValueError("repo_reading_plan_read requires paths")
    return _mcp_result(arguments, repo_reading_plan_read(
        root,
        plan_id,
        paths=paths,
        note=str(arguments.get("note") or ""),
        source=str(arguments.get("source") or "agent"),
    ))


def _handle_repo_reading_plan_diff(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    if plan_id <= 0:
        raise ValueError("repo_reading_plan_diff requires positive id")
    return _mcp_result(arguments, repo_reading_plan_diff(root, plan_id))


def _handle_repo_reading_plan_finish(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    if plan_id <= 0:
        raise ValueError("repo_reading_plan_finish requires positive id")
    return _mcp_result(arguments, repo_reading_plan_finish(
        root,
        plan_id,
        read=_string_list(arguments.get("read")),
        verified=_string_list(arguments.get("verified")),
        useful=_string_list(arguments.get("useful")),
        central=_string_list(arguments.get("central")),
        support=_string_list(arguments.get("support")),
        created=_string_list(arguments.get("created")),
        verification=_string_list(arguments.get("verification")),
        noisy=_string_list(arguments.get("noisy")),
        missing=_string_list(arguments.get("missing")),
        summary=str(arguments.get("summary") or ""),
        source=str(arguments.get("source") or "agent"),
        kind=str(arguments["kind"]) if arguments.get("kind") else None,
    ))


def _handle_repo_workstream_report(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    workstream_key = str(arguments.get("workstream_key") or "").strip()
    summary = str(arguments.get("summary") or "").strip()
    if plan_id <= 0:
        raise ValueError("repo_workstream_report requires positive id")
    if not workstream_key:
        raise ValueError("repo_workstream_report requires workstream_key")
    if not summary:
        raise ValueError("repo_workstream_report requires summary")
    return _mcp_result(arguments, repo_workstream_report(
        root,
        plan_id,
        workstream_key,
        summary,
        agent_name=str(arguments.get("agent_name") or "subagent"),
        files_read=_string_list(arguments.get("files_read")),
        files_modified=_string_list(arguments.get("files_modified")),
        tests=_string_list(arguments.get("tests")),
        findings=_string_list(arguments.get("findings")),
        risks=_string_list(arguments.get("risks")),
        remaining=_string_list(arguments.get("remaining")),
    ))


def _handle_repo_workstream_review(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    workstream_key = str(arguments.get("workstream_key") or "").strip()
    decision = str(arguments.get("decision") or "").strip()
    if plan_id <= 0:
        raise ValueError("repo_workstream_review requires positive id")
    if not workstream_key:
        raise ValueError("repo_workstream_review requires workstream_key")
    if not decision:
        raise ValueError("repo_workstream_review requires decision")
    return _mcp_result(arguments, repo_workstream_review(
        root,
        plan_id,
        workstream_key,
        decision,
        note=str(arguments.get("note") or ""),
    ))


def _handle_repo_reading_plan_mark(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    plan_id = int(arguments.get("id") or 0)
    if plan_id <= 0:
        raise ValueError("repo_reading_plan_mark requires positive id")
    kind = str(arguments.get("kind") or "").strip()
    if not kind:
        raise ValueError("repo_reading_plan_mark requires kind")
    return _mcp_result(arguments, repo_reading_plan_mark(root, plan_id, kind))


def _handle_repo_reading_plan_stats(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    return repo_reading_plan_stats(
        root,
        limit=int(arguments.get("limit") or 20),
        include_all=bool(arguments.get("include_all") or arguments.get("all") or False),
    )


def _handle_repo_overview(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    return repo_overview(root, prepare=False)


def _handle_repo_entrypoints(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 12)
    return repo_entrypoints(root, prepare=False, limit=limit)


def _handle_repo_related_file(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("repo_related_file requires path")
    return _mcp_result(arguments, repo_related_file(root, path, prepare=False))


def _handle_repo_symbol_callers(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    symbol = str(arguments.get("symbol") or "").strip()
    if not symbol:
        raise ValueError("repo_symbol_callers requires symbol")
    limit = int(arguments.get("limit") or 50)
    return _mcp_result(arguments, repo_symbol_callers(root, symbol, limit=limit, prepare=False))


def _handle_repo_feedback_add(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    path = str(arguments.get("path") or "").strip()
    rating = str(arguments.get("rating") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    source = str(arguments.get("source") or "agent").strip()
    if not query:
        raise ValueError("repo_feedback_add requires query")
    if not path:
        raise ValueError("repo_feedback_add requires path")
    if not rating:
        raise ValueError("repo_feedback_add requires rating")
    return repo_feedback_add(root, query, path, rating, reason=reason, source=source)


def _handle_repo_feedback_explain(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_feedback_explain requires query")
    include_all = bool(arguments.get("include_all") or False)
    return repo_feedback_explain(root, query, include_all=include_all)


def _handle_repo_memory_add(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    note = str(arguments.get("note") or "").strip()
    topic = str(arguments.get("topic") or "").strip()
    query = str(arguments.get("query") or "").strip()
    source = str(arguments.get("source") or "agent").strip()
    evidence = str(arguments.get("evidence") or "read_excerpt").strip()
    scope = str(arguments.get("scope") or "file").strip()
    tags = _string_list(arguments.get("tags"))
    if scope != "repo" and not path:
        raise ValueError("repo_memory_add requires path for file scope")
    if not note:
        raise ValueError("repo_memory_add requires note")
    return repo_memory_add(root, path, note, topic=topic, query=query, source=source, evidence=evidence, scope=scope, tags=tags)


def _handle_repo_memory_list(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip() or None
    topic = str(arguments.get("topic") or "").strip() or None
    scope = str(arguments.get("scope") or "").strip() or None
    stale_only = bool(arguments.get("stale_only") or False)
    limit = int(arguments.get("limit") or 20)
    return repo_memory_list(root, path=path, topic=topic, scope=scope, stale_only=stale_only, limit=limit)


def _handle_repo_memory_audit(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 100)
    return repo_memory_audit(root, limit=limit)


def _handle_repo_memory_delete(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    note_id = int(arguments.get("id") or 0)
    if note_id <= 0:
        raise ValueError("repo_memory_delete requires positive id")
    return repo_memory_delete(root, note_id)


def _handle_repo_memory_update(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    note_id = int(arguments.get("id") or 0)
    if note_id <= 0:
        raise ValueError("repo_memory_update requires positive id")
    note = str(arguments.get("note")).strip() if "note" in arguments else None
    topic = str(arguments.get("topic")).strip() if "topic" in arguments else None
    query = str(arguments.get("query")).strip() if "query" in arguments else None
    source = str(arguments.get("source")).strip() if "source" in arguments else None
    evidence = str(arguments.get("evidence")).strip() if "evidence" in arguments else None
    tags = _string_list(arguments.get("tags")) if "tags" in arguments else None
    return repo_memory_update(root, note_id, note=note, topic=topic, query=query, source=source, evidence=evidence, tags=tags, revalidate=arguments.get("revalidate", False))


def _handle_repo_memory_search(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    path = str(arguments.get("path") or "").strip() or None
    limit = int(arguments.get("limit") or 10)
    if not query:
        raise ValueError("repo_memory_search requires query")
    return repo_memory_search(root, query, path=path, limit=limit)


def _handle_repo_memory_topics(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    topic = str(arguments.get("topic") or "").strip() or None
    limit = int(arguments.get("limit") or 20)
    notes_per_topic = int(arguments.get("notes_per_topic") or 5)
    return repo_memory_topics(root, topic=topic, limit=limit, notes_per_topic=notes_per_topic)


def _handle_repo_flow_topics(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    tag = str(arguments.get("tag") or "").strip() or None
    limit = int(arguments.get("limit") or 20)
    return _mcp_result(arguments, repo_flow_topics(root, tag=tag, limit=limit))


def _handle_repo_file_notes(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    limit = int(arguments.get("limit") or 20)
    if not path:
        raise ValueError("repo_file_notes requires path")
    return repo_file_notes(root, path, limit=limit)


def _handle_repo_session_summary(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 10)
    return _mcp_result(arguments, repo_session_summary(root, limit=limit))


def _handle_repo_session_close(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 10)
    return _mcp_result(arguments, repo_session_close(root, limit=limit))


def _handle_repo_task_add(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    title = str(arguments.get("title") or "").strip()
    if not title:
        raise ValueError("repo_task_add requires title")
    return repo_task_add(
        root,
        title,
        topic=str(arguments.get("topic") or "").strip(),
        summary=str(arguments.get("summary") or "").strip(),
        files=_string_list(arguments.get("files")),
        status=str(arguments.get("status") or "open").strip(),
        source=str(arguments.get("source") or "agent").strip(),
    )


def _handle_repo_task_list(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    status = str(arguments.get("status") or "").strip() or None
    topic = str(arguments.get("topic") or "").strip() or None
    include_done = bool(arguments.get("include_done") or False)
    limit = int(arguments.get("limit") or 20)
    return repo_task_list(root, status=status, topic=topic, include_done=include_done, limit=limit)


def _handle_repo_task_note(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = int(arguments.get("id") or 0)
    note = str(arguments.get("note") or "").strip()
    if task_id <= 0:
        raise ValueError("repo_task_note requires positive id")
    if not note:
        raise ValueError("repo_task_note requires note")
    return repo_task_note(
        root,
        task_id,
        note,
        files=_string_list(arguments.get("files")),
        memory_ids=_int_list(arguments.get("memory_ids")),
        feedback_ids=_int_list(arguments.get("feedback_ids")),
        tests=_string_list(arguments.get("tests")),
        remaining=_string_list(arguments.get("remaining")),
        source=str(arguments.get("source") or "agent").strip(),
    )


def _handle_repo_task_update(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = int(arguments.get("id") or 0)
    if task_id <= 0:
        raise ValueError("repo_task_update requires positive id")
    return repo_task_update(
        root,
        task_id,
        status=str(arguments["status"]).strip() if "status" in arguments else None,
        topic=str(arguments["topic"]).strip() if "topic" in arguments else None,
        summary=str(arguments["summary"]).strip() if "summary" in arguments else None,
        files=_string_list(arguments.get("files")),
        memory_ids=_int_list(arguments.get("memory_ids")),
        feedback_ids=_int_list(arguments.get("feedback_ids")),
        tests=_string_list(arguments.get("tests")),
        remaining=_string_list(arguments.get("remaining")),
        source=str(arguments["source"]).strip() if "source" in arguments else None,
    )


def _handle_repo_task_close(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = int(arguments.get("id") or 0)
    if task_id <= 0:
        raise ValueError("repo_task_close requires positive id")
    return repo_task_close(
        root,
        task_id,
        summary=str(arguments["summary"]).strip() if "summary" in arguments else None,
        tests=_string_list(arguments.get("tests")),
        remaining=_string_list(arguments.get("remaining")),
        source=str(arguments.get("source") or "agent").strip(),
    )


def _string_list(value: Any) -> list[str]:
    validate_input(value)
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _int_list(value: Any) -> list[int]:
    validate_input(value)
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.append(parsed)
    return result


def _mcp_result(arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if bool(arguments.get("include_details") or False):
        return result
    return compact_mcp_result(result)


MCP_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "repo_graph_search": _handle_repo_graph_search,
    "repo_trace": _handle_repo_trace,
    "repo_reading_plan": _handle_repo_reading_plan,
    "repo_reading_plan_read": _handle_repo_reading_plan_read,
    "repo_reading_plan_diff": _handle_repo_reading_plan_diff,
    "repo_reading_plan_finish": _handle_repo_reading_plan_finish,
    "repo_workstream_report": _handle_repo_workstream_report,
    "repo_workstream_review": _handle_repo_workstream_review,
    "repo_reading_plan_mark": _handle_repo_reading_plan_mark,
    "repo_reading_plan_stats": _handle_repo_reading_plan_stats,
    "repo_entrypoints": _handle_repo_entrypoints,
    "repo_feedback_add": _handle_repo_feedback_add,
    "repo_feedback_explain": _handle_repo_feedback_explain,
    "repo_file_notes": _handle_repo_file_notes,
    "repo_overview": _handle_repo_overview,
    "repo_memory_add": _handle_repo_memory_add,
    "repo_memory_audit": _handle_repo_memory_audit,
    "repo_memory_delete": _handle_repo_memory_delete,
    "repo_memory_list": _handle_repo_memory_list,
    "repo_memory_search": _handle_repo_memory_search,
    "repo_memory_topics": _handle_repo_memory_topics,
    "repo_flow_topics": _handle_repo_flow_topics,
    "repo_memory_update": _handle_repo_memory_update,
    "repo_related_file": _handle_repo_related_file,
    "repo_session_close": _handle_repo_session_close,
    "repo_session_summary": _handle_repo_session_summary,
    "repo_symbol_callers": _handle_repo_symbol_callers,
    "repo_task_add": _handle_repo_task_add,
    "repo_task_close": _handle_repo_task_close,
    "repo_task_list": _handle_repo_task_list,
    "repo_task_note": _handle_repo_task_note,
    "repo_task_update": _handle_repo_task_update,
}


MCP_TOOL_HANDLERS = {name: bounded_metadata(handler) for name, handler in MCP_TOOL_HANDLERS.items()}

def mcp_tool_definitions(profile: str = "core") -> list[dict[str, Any]]:
    normalized_profile = profile.strip().lower()
    if normalized_profile not in MCP_TOOL_PROFILES:
        raise ValueError(f"unknown MCP tool profile: {profile}")
    definitions = [
        {
            "name": "repo_graph_search",
            "description": "Search the local init-agent graph for a coding task and return candidate files, symbols and follow-up commands.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text task or question."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_trace",
            "description": "Trace likely investigation paths through entry points, includes, imports and local graph relations for a coding task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text task or question."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 4},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan",
            "description": "Return a memory-, feedback-, tag- and stale-aware reading plan for a coding task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text task or question."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                    "read_budget": {"type": "integer", "minimum": 1, "maximum": 10, "default": 3},
                    "kind": {
                        "type": "string",
                        "enum": ["real", "smoke", "experiment", "planning", "diagnostic", "docs"],
                        "default": "real",
                        "description": "Plan kind for scorecard filtering.",
                    },
                    "delegate": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include optional delegated workstream advice. Disabled by default.",
                    },
                    "include_details": {"type": "boolean", "default": False, "description": "Return the full unbounded plan contract."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan_read",
            "description": "Record files the agent actually opened while following a reading plan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Files opened or inspected."},
                    "note": {"type": "string", "description": "Optional short note for this read event."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                    "include_details": {"type": "boolean", "default": False, "description": "Return the complete persisted plan."},
                },
                "required": ["id", "paths"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan_diff",
            "description": "Compare a saved reading plan with recorded read and outcome events.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "include_details": {"type": "boolean", "default": False, "description": "Return the complete persisted plan."},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan_finish",
            "description": "Finalize a reading plan with read, verified, useful, noisy and missing file outcomes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "read": {"type": "array", "items": {"type": "string"}, "description": "Files actually read."},
                    "verified": {"type": "array", "items": {"type": "string"}, "description": "Files verified."},
                    "useful": {"type": "array", "items": {"type": "string"}, "description": "Files verified useful."},
                    "central": {"type": "array", "items": {"type": "string"}, "description": "Central orientation targets."},
                    "support": {"type": "array", "items": {"type": "string"}, "description": "Supporting files used after orientation."},
                    "created": {"type": "array", "items": {"type": "string"}, "description": "Files created during the task."},
                    "verification": {"type": "array", "items": {"type": "string"}, "description": "Test or documentation verification files."},
                    "noisy": {"type": "array", "items": {"type": "string"}, "description": "Files verified noisy."},
                    "missing": {"type": "array", "items": {"type": "string"}, "description": "Important files missing from the plan."},
                    "summary": {"type": "string", "description": "Short closing summary."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                    "kind": {
                        "type": "string",
                        "enum": ["real", "smoke", "experiment", "planning", "diagnostic", "docs"],
                        "description": "Optional replacement plan kind for scorecard filtering.",
                    },
                    "include_details": {"type": "boolean", "default": False, "description": "Return full plan items and events."},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_workstream_report",
            "description": "Submit a structured delegated-workstream report for parent-orchestrator review.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "workstream_key": {"type": "string", "description": "Workstream key from the reading plan."},
                    "agent_name": {"type": "string", "default": "subagent", "description": "Worker identity or role name."},
                    "summary": {"type": "string", "description": "Concise account of completed work and conclusion."},
                    "files_read": {"type": "array", "items": {"type": "string"}},
                    "files_modified": {"type": "array", "items": {"type": "string"}},
                    "tests": {"type": "array", "items": {"type": "string"}},
                    "findings": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "remaining": {"type": "array", "items": {"type": "string"}},
                    "include_details": {"type": "boolean", "default": False},
                },
                "required": ["id", "workstream_key", "summary"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_workstream_review",
            "description": "Record the parent orchestrator's acceptance, rework request or rejection of a worker report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "workstream_key": {"type": "string", "description": "Workstream key from the reading plan."},
                    "decision": {"type": "string", "enum": ["accepted", "rework", "rejected"]},
                    "note": {"type": "string", "description": "Parent review rationale or rework instruction."},
                    "include_details": {"type": "boolean", "default": False},
                },
                "required": ["id", "workstream_key", "decision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan_mark",
            "description": "Mark a reading plan as real, smoke, experiment, planning, diagnostic or docs for scorecard filtering.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Reading plan id."},
                    "kind": {
                        "type": "string",
                        "enum": ["real", "smoke", "experiment", "planning", "diagnostic", "docs"],
                        "description": "Plan kind.",
                    },
                    "include_details": {"type": "boolean", "default": False, "description": "Return the complete persisted plan."},
                },
                "required": ["id", "kind"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_reading_plan_stats",
            "description": "Return local orientation scorecard metrics about persisted reading-plan usage.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "include_all": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_overview",
            "description": "Return a broad local repository overview with likely entry points, manifests and subsystems.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "repo_entrypoints",
            "description": "Return a focused list of likely project entry points and supporting files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 12},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_related_file",
            "description": "Inspect one indexed file neighborhood: symbols, relations, calls, callers and recent commits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path."},
                    "include_details": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return the full uncompressed neighborhood contract.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_symbol_callers",
            "description": "Return definitions and caller files for a function, method, class or symbol name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    "include_details": {
                        "type": "boolean",
                        "default": False,
                        "description": "Return the full uncompressed caller contract.",
                    },
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_feedback_add",
            "description": "Record local orientation feedback after an agent has verified whether a file was useful, noisy or missing for a query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original or similar user task/query."},
                    "path": {"type": "string", "description": "Project-relative path being evaluated."},
                    "rating": {
                        "type": "string",
                        "enum": ["crucial", "useful", "neutral", "noisy", "missing"],
                        "description": "Use missing for important files absent from the original pack; use noisy for false positives.",
                    },
                    "reason": {"type": "string", "description": "Short factual reason; do not include source code snippets."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                },
                "required": ["query", "path", "rating"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_feedback_explain",
            "description": "Explain local feedback signals that would affect a similar query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query to explain."},
                    "include_all": {"type": "boolean", "default": False, "description": "Include ignored feedback entries."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_add",
            "description": "Record a short local note about what an agent learned after verifying a repository file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path."},
                    "scope": {"type": "string", "enum": ["file", "repo"], "default": "file", "description": "Use repo for project-wide notes that are not tied to one file."},
                    "note": {"type": "string", "description": "Short factual note; do not include source code snippets."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional structured tags such as mcp or server_startup."},
                    "topic": {"type": "string", "description": "Optional topic such as badge messages or runtime entrypoints."},
                    "query": {"type": "string", "description": "Optional user task/query that led to the note."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                    "evidence": {
                        "type": "string",
                        "enum": [
                            "read_full_file",
                            "read_excerpt",
                            "manifest_only",
                            "inferred_from_graph",
                            "user_decision",
                            "implementation_note",
                            "planning_note",
                        ],
                        "default": "read_excerpt",
                        "description": "How the note was verified.",
                    },
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_list",
            "description": "List local agent file notes, optionally filtered by path, topic or stale status.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional project-relative file path filter."},
                    "topic": {"type": "string", "description": "Optional exact topic filter."},
                    "scope": {"type": "string", "enum": ["file", "repo"], "description": "Optional memory scope filter."},
                    "stale_only": {"type": "boolean", "default": False, "description": "Return only stale or unknown-staleness notes."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_audit",
            "description": "Return quality signals for local memory notes, including stale, missing-topic, unknown-evidence and duplicate groups.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_session_summary",
            "description": "Return a compact local handoff summary with git status, recent memory, recent feedback and memory audit counts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    "include_details": {"type": "boolean", "default": False, "description": "Include full recent plans, events and metadata."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_session_close",
            "description": "Return an end-of-session checklist for agent handoff, including git review, stale memory and verification prompts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    "include_details": {"type": "boolean", "default": False, "description": "Include full recent plans, events and metadata."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_search",
            "description": "Search local agent file notes for a task, topic or question.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Task, topic or question to search in local notes."},
                    "path": {"type": "string", "description": "Optional project-relative file path filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_topics",
            "description": "Return topic-level aggregates from local agent memory notes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Optional exact topic filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "notes_per_topic": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_flow_topics",
            "description": "Aggregate memory tags and indexed file tags into flow-oriented groups.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Optional exact tag filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "include_details": {"type": "boolean", "default": False, "description": "Include all note fields and longer path lists."},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_delete",
            "description": "Delete one local agent file note by id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Memory note id to delete."},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_update",
            "description": "Update a local note. Preserve the file hash unless revalidate=true after checking the current file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Memory note id to update."},
                    "revalidate": {"type": "boolean", "default": False, "description": "Renew file evidence only after re-reading and verifying the note against the current file."},
                    "note": {"type": "string", "description": "Replacement short factual note; do not include source code snippets."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Replacement structured tags."},
                    "topic": {"type": "string", "description": "Replacement topic."},
                    "query": {"type": "string", "description": "Replacement task/query that led to the note."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "description": "Replacement memory source."},
                    "evidence": {
                        "type": "string",
                        "enum": [
                            "read_full_file",
                            "read_excerpt",
                            "manifest_only",
                            "inferred_from_graph",
                            "user_decision",
                            "implementation_note",
                            "planning_note",
                        ],
                        "description": "Replacement evidence level.",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_task_add",
            "description": "Create a local task/session memory item that links ongoing work to files, tests, memories and remaining follow-up.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short task title."},
                    "status": {"type": "string", "enum": ["open", "in_progress", "blocked", "done"], "default": "open"},
                    "topic": {"type": "string", "description": "Optional functional area or topic."},
                    "summary": {"type": "string", "description": "Short task summary."},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Related project-relative files."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_task_list",
            "description": "List local task/session memory items, open by default unless include_done is true.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["open", "in_progress", "blocked", "done"], "description": "Optional status filter."},
                    "topic": {"type": "string", "description": "Optional exact topic filter."},
                    "include_done": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_task_note",
            "description": "Append a progress note to a local task/session item and optionally link files, tests, memories, feedback and remaining work.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Task id."},
                    "note": {"type": "string", "description": "Short operational note; do not include source snippets."},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Related project-relative files."},
                    "memory_ids": {"type": "array", "items": {"type": "integer"}, "description": "Related memory ids."},
                    "feedback_ids": {"type": "array", "items": {"type": "integer"}, "description": "Related feedback ids."},
                    "tests": {"type": "array", "items": {"type": "string"}, "description": "Verification performed."},
                    "remaining": {"type": "array", "items": {"type": "string"}, "description": "Remaining follow-up."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                },
                "required": ["id", "note"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_task_update",
            "description": "Update local task/session metadata such as status, summary, linked files, tests and remaining work.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Task id."},
                    "status": {"type": "string", "enum": ["open", "in_progress", "blocked", "done"]},
                    "topic": {"type": "string", "description": "Replacement topic."},
                    "summary": {"type": "string", "description": "Replacement summary."},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Related project-relative files."},
                    "memory_ids": {"type": "array", "items": {"type": "integer"}, "description": "Related memory ids."},
                    "feedback_ids": {"type": "array", "items": {"type": "integer"}, "description": "Related feedback ids."},
                    "tests": {"type": "array", "items": {"type": "string"}, "description": "Verification performed."},
                    "remaining": {"type": "array", "items": {"type": "string"}, "description": "Remaining follow-up."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"]},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_task_close",
            "description": "Mark a local task/session memory item done and optionally record closing summary, verification and remaining follow-up.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Task id."},
                    "summary": {"type": "string", "description": "Closing summary."},
                    "tests": {"type": "array", "items": {"type": "string"}, "description": "Verification performed."},
                    "remaining": {"type": "array", "items": {"type": "string"}, "description": "Known follow-up despite closing."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_file_notes",
            "description": "Return local agent notes attached to one project file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ]
    def constrain(schema):
        if schema.get("type") == "string":
            schema["maxLength"] = min(schema.get("maxLength", MAX_STRING), MAX_STRING)
        if schema.get("type") == "array":
            schema["maxItems"] = min(schema.get("maxItems", MAX_ITEMS), MAX_ITEMS)
        for value in schema.values():
            if isinstance(value, dict):
                constrain(value)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, dict):
                        constrain(child)
    for definition in definitions:
        constrain(definition["inputSchema"])
    if normalized_profile == "full":
        return definitions
    return [definition for definition in definitions if definition["name"] in MCP_CORE_TOOL_NAMES]


def mcp_tool_names(profile: str = "core") -> frozenset[str]:
    return frozenset(definition["name"] for definition in mcp_tool_definitions(profile))
