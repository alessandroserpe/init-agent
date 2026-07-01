"""Agent-facing tool contracts built on top of the local graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .contracts import TOOL_CONTRACT_VERSION
from .context_builder import build_context_pack
from .feedback import add_feedback, explain_feedback, list_feedback
from .git_reader import current_branch, git_available, status_short
from .graph_store import GraphStore
from .memory import add_note, audit_notes, delete_note, list_notes, search_notes, topic_summaries, update_note
from .overview import build_overview_pack
from .plan_feedback import (
    finish_reading_plan,
    list_reading_plans,
    reading_plan_diff,
    reading_plan_stats,
    record_reading_plan_read,
    save_reading_plan,
)
from .query import callers_for_symbol, related
from .reading_plan import build_reading_plan
from .run import run_query
from .tasks import add_task, add_task_note, close_task, list_tasks, update_task
from .trace import trace_query
from .utils import db_path, ensure_agent_dir
from .session_tools import repo_session_close, repo_session_summary
from .renderers import (
    render_repo_graph_search_text,
    render_repo_trace_text,
    render_repo_reading_plan_text,
    render_repo_reading_plan_finish_text,
    render_repo_reading_plan_read_text,
    render_repo_reading_plan_diff_text,
    render_repo_reading_plan_stats_text,
    render_repo_related_file_text,
    render_repo_symbol_callers_text,
    render_repo_overview_text,
    render_repo_entrypoints_text,
    render_repo_feedback_add_text,
    render_repo_feedback_explain_text,
    render_repo_memory_add_text,
    render_repo_memory_search_text,
    render_repo_file_notes_text,
    render_repo_memory_list_text,
    render_repo_memory_topics_text,
    render_repo_flow_topics_text,
    render_repo_memory_audit_text,
    render_repo_memory_delete_text,
    render_repo_memory_update_text,
    render_repo_task_add_text,
    render_repo_task_list_text,
    render_repo_task_update_text,
    render_repo_task_note_text,
    render_repo_session_summary_text,
    render_repo_session_close_text,
)



def repo_graph_search(root: Path, query: str, limit: int = 10, prepare: bool = True) -> dict[str, Any]:
    """Return a compact JSON contract for agent graph search."""

    bounded_limit = max(1, min(limit, 20))
    if prepare:
        run_result = run_query(root, query, overview=False)
        context = run_result.get("context", {})
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
        context = build_context_pack(root, query) if readiness["ready"] else _empty_context(query)
    candidate_files = list(context.get("candidate_files", []))[:bounded_limit]
    symbols = list(context.get("related_symbols", []))[:10]
    related_commits = list(context.get("recent_commits", []))[:5]
    return {
        "tool": "repo_graph_search",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "preparation": preparation,
        "candidate_files": candidate_files,
        "suggested_first_reads": [item["path"] for item in candidate_files[:5]],
        "symbols": symbols,
        "related_commits": related_commits,
        "confidence": context.get("confidence", {}),
        "next_agent_actions": context.get("next_agent_actions", []),
        "followup_commands": _followup_commands(query, candidate_files, symbols),
        "warnings": warnings,
    }


def repo_related_file(root: Path, path: str, prepare: bool = True) -> dict[str, Any]:
    """Return a compact JSON contract for one indexed file neighborhood."""

    normalized_path = Path(path).as_posix().lstrip("./")
    if prepare:
        run_result = run_query(root, f"related file {normalized_path}", overview=False)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
    related_data = related(root, normalized_path) if prepare or readiness["ready"] else None
    result = {
        "tool": "repo_related_file",
        "contract": TOOL_CONTRACT_VERSION,
        "path": normalized_path,
        "preparation": preparation,
        "file": None,
        "symbols": [],
        "relations": [],
        "calls": [],
        "called_by": [],
        "recent_commits": [],
        "cochanged_files": [],
        "followup_commands": [],
        "warnings": warnings,
    }
    if related_data is None:
        result["warnings"].append(f"file not found in index: {normalized_path}")
        return result
    result.update(
        {
            "file": _trim_file_record(related_data["file"]),
            "symbols": list(related_data["symbols"])[:30],
            "relations": list(related_data["relations"])[:30],
            "calls": list(related_data["resolved_calls"])[:30],
            "called_by": list(related_data["callers"])[:30],
            "recent_commits": _compact_commits(list(related_data["commits"])[:5]),
            "cochanged_files": list(related_data["cochanged_files"])[:20],
            "followup_commands": _related_followup_commands(normalized_path, related_data),
        }
    )
    return result


def repo_symbol_callers(root: Path, symbol: str, limit: int = 50, prepare: bool = True) -> dict[str, Any]:
    """Return a compact JSON contract for symbol definitions and callers."""

    normalized_symbol = symbol.strip()
    bounded_limit = max(1, min(limit, 100))
    if prepare:
        run_result = run_query(root, f"symbol callers {normalized_symbol}", overview=False)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
    data = callers_for_symbol(root, normalized_symbol, limit=bounded_limit) if prepare or readiness["ready"] else {
        "symbol": normalized_symbol,
        "definitions": [],
        "callers": [],
    }
    return {
        "tool": "repo_symbol_callers",
        "contract": TOOL_CONTRACT_VERSION,
        "symbol": data["symbol"],
        "preparation": preparation,
        "definitions": list(data["definitions"]),
        "callers": list(data["callers"]),
        "followup_commands": _symbol_followup_commands(data),
        "warnings": warnings,
    }


def repo_overview(root: Path, prepare: bool = True) -> dict[str, Any]:
    """Return a compact JSON contract for broad repository orientation."""

    if prepare:
        run_result = run_query(root, "repository overview", overview=True)
        overview = run_result.get("overview") or build_overview_pack(root)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        overview = build_overview_pack(root) if readiness["ready"] else _empty_overview(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
    return {
        "tool": "repo_overview",
        "contract": TOOL_CONTRACT_VERSION,
        "preparation": preparation,
        "project": overview.get("project", {}),
        "suggested_first_reads": overview.get("suggested_first_reads", []),
        "entry_points": overview.get("entry_points", []),
        "manifests": overview.get("manifests", []),
        "subsystems": overview.get("subsystems", []),
        "followup_commands": _overview_followup_commands(overview),
        "warnings": warnings,
    }


def repo_entrypoints(root: Path, prepare: bool = True, limit: int = 12) -> dict[str, Any]:
    """Return a focused JSON contract for likely project entry points."""

    bounded_limit = max(1, min(limit, 30))
    if prepare:
        run_result = run_query(root, "repository entrypoints startup runtime", overview=True)
        overview = run_result.get("overview") or build_overview_pack(root)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        overview = build_overview_pack(root) if readiness["ready"] else _empty_overview(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])

    entry_points = _focused_entry_points(list(overview.get("entry_points", [])), bounded_limit)
    suggested = list(overview.get("suggested_first_reads", []))
    manifests = list(overview.get("manifests", []))[:10]
    entry_paths = {str(item.get("path") or "") for item in entry_points}
    supporting_files = [
        item for item in suggested
        if str(item.get("path") or "") not in entry_paths
    ][: max(0, bounded_limit - len(entry_points))]
    return {
        "tool": "repo_entrypoints",
        "contract": TOOL_CONTRACT_VERSION,
        "preparation": preparation,
        "project": overview.get("project", {}),
        "entry_points": entry_points,
        "supporting_files": supporting_files,
        "manifests": manifests,
        "followup_commands": _entrypoint_followup_commands(entry_points, supporting_files),
        "warnings": warnings,
    }


def repo_trace(root: Path, query: str, limit: int = 10, max_depth: int = 4, prepare: bool = True) -> dict[str, Any]:
    """Return likely investigation paths through the local graph."""

    bounded_limit = max(1, min(limit, 30))
    bounded_depth = max(1, min(max_depth, 6))
    if prepare:
        run_result = run_query(root, f"trace {query}", overview=False)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
    trace = trace_query(root, query, limit=bounded_limit, max_depth=bounded_depth) if prepare or readiness["ready"] else {
        "query": query,
        "profile": "entrypoint_trace",
        "starts": [],
        "paths": [],
        "suggested_first_reads": [],
        "warnings": [],
    }
    return {
        "tool": "repo_trace",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "preparation": preparation,
        "profile": trace.get("profile", "entrypoint_trace"),
        "starts": trace.get("starts", []),
        "paths": trace.get("paths", []),
        "suggested_first_reads": trace.get("suggested_first_reads", []),
        "followup_commands": _trace_followup_commands(trace.get("paths", [])),
        "warnings": [*warnings, *trace.get("warnings", [])],
    }


def repo_reading_plan(root: Path, query: str, limit: int = 10, read_budget: int = 3, prepare: bool = True, source: str = "agent") -> dict[str, Any]:
    """Return a reading plan composed from graph, trace, memory, feedback and tags."""

    bounded_limit = max(1, min(limit, 30))
    bounded_read_budget = max(1, min(read_budget, 10))
    if prepare:
        run_result = run_query(root, f"reading plan {query}", overview=False)
        preparation = run_result.get("preparation", {})
        warnings = _warnings(run_result)
    else:
        readiness = _readiness(root)
        preparation = _lazy_preparation(readiness["warnings"])
        warnings = list(readiness["warnings"])
    plan = build_reading_plan(root, query, limit=bounded_limit) if prepare or readiness["ready"] else {
        "query": query,
        "query_tokens": [],
        "plan_items": [],
        "memory_matches": [],
        "repo_memory_context": [],
        "recommended_actions": [],
        "warnings": [],
    }
    if prepare or readiness["ready"]:
        plan = build_reading_plan(root, query, limit=bounded_limit, read_budget=bounded_read_budget)
        saved_plan = save_reading_plan(root, query, plan.get("plan_items", []), bounded_read_budget, source=source)
    else:
        saved_plan = None
    return {
        "tool": "repo_reading_plan",
        "contract": TOOL_CONTRACT_VERSION,
        "id": saved_plan["id"] if saved_plan else None,
        "query": query,
        "preparation": preparation,
        "read_budget": bounded_read_budget,
        "query_tokens": plan.get("query_tokens", []),
        "plan_items": plan.get("plan_items", []),
        "memory_matches": plan.get("memory_matches", []),
        "repo_memory_context": plan.get("repo_memory_context", []),
        "recommended_actions": plan.get("recommended_actions", []),
        "warnings": [*warnings, *plan.get("warnings", [])],
    }


def repo_reading_plan_finish(
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
    """Record how a reading plan performed after files were verified."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    finished = (
        finish_reading_plan(
            root,
            plan_id,
            read=read or [],
            verified=verified or [],
            useful=useful or [],
            noisy=noisy or [],
            missing=missing or [],
            summary=summary,
            source=source,
        )
        if readiness["ready"]
        else {"updated": False, "id": plan_id, "plan": None, "events": [], "feedback": [], "suggested_memory": []}
    )
    return {
        "tool": "repo_reading_plan_finish",
        "contract": TOOL_CONTRACT_VERSION,
        **finished,
        "warnings": warnings,
        "safety": [
            "finish a reading plan only after actually reading or verifying files",
            "feedback is created only for explicit useful, noisy and missing paths",
        ],
    }


def repo_reading_plan_read(root: Path, plan_id: int, paths: list[str], note: str = "", source: str = "agent") -> dict[str, Any]:
    """Record files opened while following a saved reading plan."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    normalized_paths = [Path(path).as_posix().lstrip("./") for path in paths if str(path).strip()]
    read = (
        record_reading_plan_read(root, plan_id, normalized_paths, note=note, source=source)
        if readiness["ready"]
        else {"updated": False, "id": plan_id, "plan": None, "events": []}
    )
    return {
        "tool": "repo_reading_plan_read",
        "contract": TOOL_CONTRACT_VERSION,
        **read,
        "warnings": warnings,
        "safety": [
            "record only files actually opened or inspected by the agent",
            "this is metadata-only tracking; it does not read source files for you",
        ],
    }


def repo_reading_plan_diff(root: Path, plan_id: int) -> dict[str, Any]:
    """Return the gap between a saved reading plan and recorded agent activity."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    diff = reading_plan_diff(root, plan_id) if readiness["ready"] else {
        "id": plan_id,
        "found": False,
        "plan": None,
        "diff": {},
    }
    return {
        "tool": "repo_reading_plan_diff",
        "contract": TOOL_CONTRACT_VERSION,
        **diff,
        "warnings": warnings,
        "safety": [
            "diff is based on recorded plan events, not automatic editor telemetry",
            "verify files before converting diff output into feedback or memory",
        ],
    }


def repo_reading_plan_stats(root: Path) -> dict[str, Any]:
    """Return optional local metrics for persisted reading plans."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    stats = reading_plan_stats(root) if readiness["ready"] else {}
    return {
        "tool": "repo_reading_plan_stats",
        "contract": TOOL_CONTRACT_VERSION,
        "stats": stats,
        "warnings": warnings,
    }


def repo_feedback_add(
    root: Path,
    query: str,
    path: str,
    rating: str,
    reason: str = "",
    source: str = "agent",
) -> dict[str, Any]:
    """Record local orientation feedback after an agent verifies a file."""

    readiness = _readiness(root)
    warnings = list(readiness["warnings"])
    result: dict[str, Any] = {
        "tool": "repo_feedback_add",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "path": Path(path).as_posix().lstrip("./"),
        "rating": rating,
        "source": source,
        "recorded": False,
        "feedback": None,
        "warnings": warnings,
        "safety": [
            "record feedback only after reading or otherwise verifying the file",
            "store factual reasons only; do not include source code snippets",
        ],
    }
    if not readiness["ready"]:
        return result
    record = add_feedback(root, query, path, rating, reason=reason, source=source)
    result.update(
        {
            "path": record["path"],
            "rating": record["rating"],
            "source": record["source"],
            "recorded": True,
            "feedback": record,
        }
    )
    return result


def repo_feedback_explain(root: Path, query: str, include_all: bool = False) -> dict[str, Any]:
    """Explain local feedback signals for a future or repeated query."""

    readiness = _readiness(root)
    warnings = list(readiness["warnings"])
    explanation = explain_feedback(root, query, include_all=include_all) if readiness["ready"] else {
        "query": query,
        "query_tokens": [],
        "min_similarity": 0.0,
        "signals": [],
        "ignored": [],
    }
    return {
        "tool": "repo_feedback_explain",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "feedback": explanation,
        "warnings": warnings,
    }


def repo_memory_add(
    root: Path,
    path: str | None,
    note: str,
    topic: str = "",
    query: str = "",
    source: str = "agent",
    evidence: str = "read_excerpt",
    scope: str = "file",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Record a local file note after an agent understands a file."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    normalized_path = Path(path).as_posix().lstrip("./") if path else ""
    result: dict[str, Any] = {
        "tool": "repo_memory_add",
        "contract": TOOL_CONTRACT_VERSION,
        "scope": scope,
        "path": normalized_path,
        "topic": topic,
        "query": query,
        "source": source,
        "evidence": evidence,
        "tags": tags or [],
        "recorded": False,
        "memory": None,
        "warnings": warnings,
        "safety": [
            "record memory only after reading or otherwise verifying the file",
            "store short factual notes only; do not include source code snippets",
        ],
    }
    if not readiness["ready"]:
        return result
    record = add_note(root, normalized_path, note, topic=topic, query=query, source=source, evidence=evidence, scope=scope, tags=tags)
    result.update(
        {
            "scope": record["scope"],
            "path": record["path"],
            "topic": record["topic"],
            "query": record["query"],
            "source": record["source"],
            "evidence": record["evidence"],
            "tags": record.get("tags", []),
            "recorded": True,
            "memory": record,
        }
    )
    return result


def repo_memory_search(root: Path, query: str, path: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Search local file notes for a task or topic."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    memory = search_notes(root, query, path=path, limit=limit) if readiness["ready"] else {
        "query": query,
        "query_tokens": [],
        "path": path,
        "matches": [],
    }
    return {
        "tool": "repo_memory_search",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "memory": memory,
        "warnings": warnings,
    }


def repo_memory_list(
    root: Path,
    path: str | None = None,
    topic: str | None = None,
    scope: str | None = None,
    stale_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """List local file notes, optionally filtered by file, topic or stale status."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    normalized_path = Path(path).as_posix().lstrip("./") if path else None
    notes = (
        list_notes(root, path=normalized_path, topic=topic, scope=scope, stale_only=stale_only, limit=limit)
        if readiness["ready"]
        else []
    )
    return {
        "tool": "repo_memory_list",
        "contract": TOOL_CONTRACT_VERSION,
        "path": normalized_path,
        "topic": topic or None,
        "scope": scope or None,
        "stale_only": stale_only,
        "notes": notes,
        "warnings": warnings,
    }


def repo_memory_topics(
    root: Path,
    topic: str | None = None,
    limit: int = 20,
    notes_per_topic: int = 5,
) -> dict[str, Any]:
    """Return compact topic-level aggregates from local memory notes."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    memory = (
        topic_summaries(root, topic=topic, limit=limit, notes_per_topic=notes_per_topic)
        if readiness["ready"]
        else {"topic": topic or None, "topics": []}
    )
    return {
        "tool": "repo_memory_topics",
        "contract": TOOL_CONTRACT_VERSION,
        "memory": memory,
        "warnings": warnings,
    }


def repo_flow_topics(root: Path, tag: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Aggregate local memories and indexed file tags into flow-oriented groups."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    flows = _flow_topics(root, tag=tag, limit=limit) if readiness["ready"] else {"tag": tag or None, "flows": []}
    return {
        "tool": "repo_flow_topics",
        "contract": TOOL_CONTRACT_VERSION,
        "flows": flows,
        "warnings": warnings,
    }


def repo_memory_audit(root: Path, limit: int = 100) -> dict[str, Any]:
    """Return quality signals for local memory notes."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    audit = audit_notes(root, limit=limit) if readiness["ready"] else {
        "note_count": 0,
        "summary": {},
        "issues": {},
    }
    return {
        "tool": "repo_memory_audit",
        "contract": TOOL_CONTRACT_VERSION,
        "audit": audit,
        "warnings": warnings,
    }


def repo_memory_delete(root: Path, note_id: int) -> dict[str, Any]:
    """Delete one local file note by id."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    deleted = delete_note(root, note_id) if readiness["ready"] else {"deleted": False, "id": note_id, "note": None}
    return {
        "tool": "repo_memory_delete",
        "contract": TOOL_CONTRACT_VERSION,
        **deleted,
        "warnings": warnings,
    }


def repo_memory_update(
    root: Path,
    note_id: int,
    note: str | None = None,
    topic: str | None = None,
    query: str | None = None,
    source: str | None = None,
    evidence: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Update one local memory note and refresh its file hash when applicable."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    updated = (
        update_note(root, note_id, note=note, topic=topic, query=query, source=source, evidence=evidence, tags=tags)
        if readiness["ready"]
        else {"updated": False, "id": note_id, "memory": None}
    )
    return {
        "tool": "repo_memory_update",
        "contract": TOOL_CONTRACT_VERSION,
        **updated,
        "warnings": warnings,
        "safety": [
            "update memory only after re-checking the relevant file or project decision",
            "store short factual notes only; do not include source code snippets",
        ],
    }


def repo_file_notes(root: Path, path: str, limit: int = 20) -> dict[str, Any]:
    """Return local notes attached to one project file."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    normalized_path = Path(path).as_posix().lstrip("./")
    notes = list_notes(root, path=normalized_path, limit=limit) if readiness["ready"] else []
    return {
        "tool": "repo_file_notes",
        "contract": TOOL_CONTRACT_VERSION,
        "path": normalized_path,
        "notes": notes,
        "warnings": warnings,
    }


def repo_task_add(
    root: Path,
    title: str,
    topic: str = "",
    summary: str = "",
    files: list[str] | None = None,
    status: str = "open",
    source: str = "agent",
) -> dict[str, Any]:
    """Create a local task/session memory item for ongoing agent work."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    result: dict[str, Any] = {
        "tool": "repo_task_add",
        "contract": TOOL_CONTRACT_VERSION,
        "recorded": False,
        "task": None,
        "warnings": warnings,
        "safety": [
            "tasks are local operational memory, not a replacement for issue trackers",
            "store concise task context only; do not include source code snippets",
        ],
    }
    if not readiness["ready"]:
        return result
    task = add_task(root, title, topic=topic, summary=summary, files=files or [], status=status, source=source)
    result.update({"recorded": True, "task": task})
    return result


def repo_task_list(
    root: Path,
    status: str | None = None,
    topic: str | None = None,
    include_done: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    """List local task/session memory items."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    tasks = list_tasks(root, status=status, topic=topic, include_done=include_done, limit=limit) if readiness["ready"] else []
    return {
        "tool": "repo_task_list",
        "contract": TOOL_CONTRACT_VERSION,
        "status": status or None,
        "topic": topic or None,
        "include_done": include_done,
        "tasks": tasks,
        "warnings": warnings,
    }


def repo_task_update(
    root: Path,
    task_id: int,
    status: str | None = None,
    topic: str | None = None,
    summary: str | None = None,
    files: list[str] | None = None,
    memory_ids: list[int] | None = None,
    feedback_ids: list[int] | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Update local task/session metadata."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    updated = (
        update_task(
            root,
            task_id,
            status=status,
            topic=topic,
            summary=summary,
            files=files,
            memory_ids=memory_ids,
            feedback_ids=feedback_ids,
            tests=tests,
            remaining=remaining,
            source=source,
        )
        if readiness["ready"]
        else {"updated": False, "id": task_id, "task": None}
    )
    return {
        "tool": "repo_task_update",
        "contract": TOOL_CONTRACT_VERSION,
        **updated,
        "warnings": warnings,
    }


def repo_task_note(
    root: Path,
    task_id: int,
    note: str,
    files: list[str] | None = None,
    memory_ids: list[int] | None = None,
    feedback_ids: list[int] | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    """Append a progress note to a local task/session memory item."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    recorded = (
        add_task_note(
            root,
            task_id,
            note,
            files=files or [],
            memory_ids=memory_ids or [],
            feedback_ids=feedback_ids or [],
            tests=tests or [],
            remaining=remaining or [],
            source=source,
        )
        if readiness["ready"]
        else {"recorded": False, "id": task_id, "note": None, "task": None}
    )
    return {
        "tool": "repo_task_note",
        "contract": TOOL_CONTRACT_VERSION,
        **recorded,
        "warnings": warnings,
        "safety": [
            "record task notes after real investigation, verification or implementation progress",
            "store concise operational facts only; do not include source code snippets",
        ],
    }


def repo_task_close(
    root: Path,
    task_id: int,
    summary: str | None = None,
    tests: list[str] | None = None,
    remaining: list[str] | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    """Mark a local task/session memory item as done."""

    readiness = _memory_readiness(root)
    warnings = list(readiness["warnings"])
    closed = (
        close_task(root, task_id, summary=summary, tests=tests or [], remaining=remaining or [], source=source)
        if readiness["ready"]
        else {"updated": False, "id": task_id, "task": None}
    )
    return {
        "tool": "repo_task_close",
        "contract": TOOL_CONTRACT_VERSION,
        "closed": bool(closed.get("updated")),
        **closed,
        "warnings": warnings,
    }


def _readiness(root: Path) -> dict[str, Any]:
    db_path = root / ".agent" / "graph.sqlite"
    if not db_path.is_file():
        return {"ready": False, "warnings": ["init-agent index not found. Run: init-agent run --overview --markdown"]}
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    except sqlite3.Error as exc:
        return {"ready": False, "warnings": [f"init-agent index could not be read: {exc}"]}
    finally:
        if conn is not None:
            conn.close()
    if files <= 0:
        return {"ready": False, "warnings": ["init-agent index is empty. Run: init-agent run --overview --markdown"]}
    return {"ready": True, "warnings": []}


def _memory_readiness(root: Path) -> dict[str, Any]:
    database = db_path(root)
    warnings: list[str] = []
    index_existed = database.is_file()
    try:
        ensure_agent_dir(root)
        with GraphStore(root) as store:
            store.initialize()
            files = store.connection.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    except (OSError, sqlite3.Error) as exc:
        return {"ready": False, "warnings": [f"init-agent memory store could not be read: {exc}"]}
    if not index_existed:
        warnings.append("init-agent index not found; created local memory store without file index")
    if files <= 0:
        warnings.append("init-agent index has no files; file-scoped memories may be stale until map runs")
    return {"ready": True, "warnings": warnings}


def _compact_memory_note(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note["id"],
        "path": note.get("path", ""),
        "scope": note.get("scope", "file"),
        "topic": note.get("topic", ""),
        "query": note.get("query", ""),
        "note": note.get("note", ""),
        "tags": list(note.get("tags") or []),
        "file_sha256": note.get("file_sha256", ""),
        "current_file_sha256": note.get("current_file_sha256", ""),
        "stale": note.get("stale"),
        "stale_reason": note.get("stale_reason", ""),
        "evidence": note.get("evidence", "unknown"),
        "source": note.get("source", "agent"),
        "created_at": note.get("created_at", ""),
    }


def _flow_topics(root: Path, tag: str | None = None, limit: int = 20) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 100))
    selected = tag.strip().lower() if tag else None
    notes = list_notes(root, limit=500)
    groups: dict[str, dict[str, Any]] = {}

    def group(name: str) -> dict[str, Any]:
        return groups.setdefault(
            name,
            {
                "tag": name,
                "paths": set(),
                "notes": [],
                "stale_count": 0,
                "file_tag_count": 0,
                "memory_tag_count": 0,
            },
        )

    for note in notes:
        for note_tag in note.get("tags") or []:
            name = str(note_tag).lower()
            if selected and name != selected:
                continue
            item = group(name)
            if note.get("path"):
                item["paths"].add(str(note["path"]))
            item["notes"].append(_compact_memory_note(note))
            item["memory_tag_count"] += 1
            if note.get("stale") is True:
                item["stale_count"] += 1

    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            """
            SELECT f.path, t.tag
            FROM file_tags t
            JOIN files f ON f.id = t.file_id
            ORDER BY f.path, t.tag
            """
        ).fetchall()
    for row in rows:
        name = str(row["tag"]).lower()
        if selected and name != selected:
            continue
        item = group(name)
        item["paths"].add(str(row["path"]))
        item["file_tag_count"] += 1

    flows = []
    for item in groups.values():
        paths = sorted(item["paths"])
        notes_for_output = list(item["notes"])[:5]
        needs_summary = len(paths) >= 3 and not any(note.get("scope") == "repo" for note in notes_for_output)
        flows.append(
            {
                "tag": item["tag"],
                "file_count": len(paths),
                "paths": paths[:12],
                "note_count": len(item["notes"]),
                "stale_count": int(item["stale_count"]),
                "file_tag_count": int(item["file_tag_count"]),
                "memory_tag_count": int(item["memory_tag_count"]),
                "notes": notes_for_output,
                "suggested_flow_memory": (
                    {
                        "command": f"init-agent tool repo_memory_add --scope repo --topic {_shell_double_quote(item['tag'])} --tag {_shell_double_quote(item['tag'])} --evidence inferred_from_graph --note <flow-summary> --json",
                        "reason": "multiple files share this tag; add a repo-scoped flow note only after verification",
                    }
                    if needs_summary
                    else None
                ),
            }
        )
    flows.sort(key=lambda item: (-int(item["note_count"]), -int(item["file_count"]), str(item["tag"])))
    return {"tag": selected, "flows": flows[:bounded_limit]}


def _lazy_preparation(warnings: list[str]) -> dict[str, Any]:
    return {
        "init": "skipped",
        "map": "skipped",
        "refresh": "skipped",
        "git": "skipped",
        "warnings": warnings,
    }


def _empty_context(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "candidate_files": [],
        "suggested_first_reads": [],
        "related_symbols": [],
        "recent_commits": [],
        "confidence": {"level": "low", "reasons": ["no candidate files were found"]},
        "next_agent_actions": [
            {
                "action": "check_index",
                "command": "init-agent doctor",
                "reason": "verify whether the local index is missing, stale or unhealthy",
            },
            {
                "action": "refresh_index",
                "command": "init-agent map",
                "reason": "rebuild the map if doctor reports missing, empty or stale index data",
            },
        ],
    }


def _empty_overview(root: Path) -> dict[str, Any]:
    return {
        "project": {"name": root.name, "root": str(root), "git": False, "branch": None, "last_map": None},
        "suggested_first_reads": [],
        "entry_points": [],
        "manifests": [],
        "subsystems": [],
    }


def _followup_commands(query: str, candidate_files: list[dict[str, Any]], symbols: list[dict[str, Any]]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in candidate_files[:3]:
        path = str(item.get("path") or "")
        if path and path not in seen_paths:
            seen_paths.add(path)
            commands.append(
                {
                    "tool": "repo_related_file",
                    "command": f"init-agent tool repo_related_file --path {_shell_double_quote(path)} --json",
                    "reason": "inspect file symbols, relations, callers and recent commits",
                }
            )
    seen_symbols: set[str] = set()
    for symbol in symbols[:5]:
        name = str(symbol.get("name") or "")
        kind = str(symbol.get("kind") or "")
        if name and name not in seen_symbols and kind in {"function", "method", "class"}:
            seen_symbols.add(name)
            commands.append(
                {
                    "tool": "repo_symbol_callers",
                    "command": f"init-agent tool repo_symbol_callers --symbol {_shell_double_quote(name)} --json",
                    "reason": "inspect definitions and caller files for a relevant symbol",
                }
            )
    if candidate_files:
        first_path = str(candidate_files[0].get("path") or "")
        if first_path:
            commands.append(
                {
                    "tool": "repo_feedback_add",
                    "command": (
                        "init-agent tool repo_feedback_add "
                        f"--query {_shell_double_quote(query)} --path {_shell_double_quote(first_path)} "
                        '--rating useful --source agent --reason "verified relevant" --json'
                    ),
                    "reason": "record local feedback only after verifying the file",
                }
            )
    return commands


def _trace_followup_commands(paths: list[dict[str, Any]]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in paths:
        path = str(item.get("target") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        commands.append(
            {
                "tool": "repo_related_file",
                "command": f"init-agent tool repo_related_file --path {_shell_double_quote(path)} --json",
                "reason": "inspect the traced target file neighborhood before editing",
            }
        )
        if len(commands) >= 5:
            break
    return commands


def _related_followup_commands(path: str, related_data: dict[str, Any]) -> list[dict[str, str]]:
    commands = [
        {
            "tool": "repo_graph_search",
            "command": f"init-agent tool repo_graph_search --query {_shell_double_quote(path)} --json",
            "reason": "search around this file path and nearby terms",
        }
    ]
    seen_symbols: set[str] = set()
    for symbol in related_data.get("symbols", [])[:5]:
        name = str(symbol.get("name") or "")
        kind = str(symbol.get("kind") or "")
        if name and name not in seen_symbols and kind in {"function", "method", "class"}:
            seen_symbols.add(name)
            commands.append(
                {
                    "tool": "repo_symbol_callers",
                    "command": f"init-agent tool repo_symbol_callers --symbol {_shell_double_quote(name)} --json",
                    "reason": "inspect where a symbol from this file is called",
                }
            )
    return commands


def _symbol_followup_commands(data: dict[str, Any]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in [*data.get("definitions", []), *data.get("callers", [])]:
        path = str(item.get("path") or "")
        if path and path not in seen_paths:
            seen_paths.add(path)
            commands.append(
                {
                    "tool": "repo_related_file",
                    "command": f"init-agent tool repo_related_file --path {_shell_double_quote(path)} --json",
                    "reason": "inspect file neighborhood for this definition or caller",
                }
            )
        if len(commands) >= 5:
            break
    return commands


def _overview_followup_commands(overview: dict[str, Any]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for item in overview.get("suggested_first_reads", [])[:5]:
        path = str(item.get("path") or "")
        if path:
            commands.append(
                {
                    "tool": "repo_related_file",
                    "command": f"init-agent tool repo_related_file --path {_shell_double_quote(path)} --json",
                    "reason": "inspect a likely entry file neighborhood",
                }
            )
    return commands


def _focused_entry_points(entries: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in entries:
        path = str(item.get("path") or "")
        kind = str(item.get("kind") or "")
        if kind in {"heading", "command_example"}:
            continue
        if Path(path).suffix.lower() in {".md", ".rst", ".txt"}:
            continue
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _entrypoint_followup_commands(entry_points: list[dict[str, Any]], supporting_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in [*entry_points, *supporting_files]:
        path = str(item.get("path") or "")
        if path and path not in seen_paths:
            seen_paths.add(path)
            commands.append(
                {
                    "tool": "repo_related_file",
                    "command": f"init-agent tool repo_related_file --path {_shell_double_quote(path)} --json",
                    "reason": "inspect entry-point symbols, imports, calls and callers",
                }
            )
        if len(commands) >= 6:
            break
    return commands


def _trim_file_record(file_item: dict[str, Any]) -> dict[str, Any]:
    keys = ("path", "extension", "language", "role", "size", "sha256", "modified_at", "indexed_at")
    return {key: file_item.get(key) for key in keys}


def _compact_commits(commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "hash": commit.get("hash"),
            "author": commit.get("author"),
            "date": commit.get("date"),
            "message": commit.get("message"),
        }
        for commit in commits
    ]


def _warnings(run_result: dict[str, Any]) -> list[str]:
    preparation = run_result.get("preparation", {})
    warnings = list(preparation.get("warnings", []))
    warnings.extend(
        [
            "heuristic orientation only; verify files before editing",
            "no source code was sent to an LLM by init-agent",
        ]
    )
    return warnings


def _shell_double_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
