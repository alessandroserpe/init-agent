"""Agent-facing tool contracts built on top of the local graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
from .feedback import add_feedback, explain_feedback, list_feedback
from .git_reader import current_branch, git_available, status_short
from .graph_store import GraphStore
from .memory import add_note, audit_notes, delete_note, list_notes, search_notes, topic_summaries, update_note
from .overview import build_overview_pack
from .query import callers_for_symbol, related
from .reading_plan import build_reading_plan
from .run import run_query
from .tasks import add_task, add_task_note, close_task, list_tasks, update_task
from .trace import trace_query
from .utils import db_path, ensure_agent_dir


TOOL_CONTRACT_VERSION = "init-agent.tool.v1"


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


def repo_reading_plan(root: Path, query: str, limit: int = 10, prepare: bool = True) -> dict[str, Any]:
    """Return a reading plan composed from graph, trace, memory, feedback and tags."""

    bounded_limit = max(1, min(limit, 30))
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
    return {
        "tool": "repo_reading_plan",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "preparation": preparation,
        "query_tokens": plan.get("query_tokens", []),
        "plan_items": plan.get("plan_items", []),
        "memory_matches": plan.get("memory_matches", []),
        "repo_memory_context": plan.get("repo_memory_context", []),
        "recommended_actions": plan.get("recommended_actions", []),
        "warnings": [*warnings, *plan.get("warnings", [])],
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


def repo_session_summary(root: Path, limit: int = 10) -> dict[str, Any]:
    """Return local metadata useful at the end of an agent session."""

    bounded_limit = max(1, min(limit, 50))
    readiness = _readiness(root)
    memory_readiness = _memory_readiness(root)
    warnings = list(dict.fromkeys([*readiness["warnings"], *memory_readiness["warnings"]]))
    git_is_available = git_available(root)
    recent_memory = (
        [_compact_memory_note(note) for note in list_notes(root, limit=bounded_limit)]
        if memory_readiness["ready"]
        else []
    )
    audit = audit_notes(root, limit=100) if memory_readiness["ready"] else {
        "note_count": 0,
        "summary": {},
        "issues": {},
    }
    recent_feedback = (
        [_compact_feedback(item) for item in list_feedback(root)[:bounded_limit]]
        if readiness["ready"]
        else []
    )
    recent_tasks = (
        [_compact_task(item) for item in list_tasks(root, include_done=False, limit=bounded_limit)]
        if memory_readiness["ready"]
        else []
    )
    git = {
        "available": git_is_available,
        "branch": current_branch(root) if git_is_available else None,
        "status": status_short(root)[:bounded_limit] if git_is_available else [],
    }
    followups: list[dict[str, str]] = []
    if recent_memory:
        followups.append(
            {
                "tool": "repo_memory_audit",
                "command": "init-agent tool repo_memory_audit --json",
                "reason": "check whether recently used local memory is stale or low quality",
            }
        )
    if git["status"]:
        followups.append(
            {
                "tool": "git_status",
                "command": "git status --short",
                "reason": "review modified files before committing or ending the session",
            }
        )
    return {
        "tool": "repo_session_summary",
        "contract": TOOL_CONTRACT_VERSION,
        "project": _project_summary(root),
        "git": git,
        "recent_memory": recent_memory,
        "recent_feedback": recent_feedback,
        "recent_tasks": recent_tasks,
        "memory_audit": {
            "note_count": audit.get("note_count", 0),
            "summary": audit.get("summary", {}),
        },
        "followup_commands": followups,
        "warnings": warnings,
        "safety": [
            "summary is local metadata only; verify files before editing",
            "does not replace git status, tests or direct file reads",
        ],
    }


def repo_session_close(root: Path, limit: int = 10) -> dict[str, Any]:
    """Return an end-of-session checklist and handoff summary for agents."""

    summary = repo_session_summary(root, limit=limit)
    git = summary.get("git") or {}
    audit_summary = (summary.get("memory_audit") or {}).get("summary") or {}
    status_count = len(git.get("status") or [])
    task_count = len(summary.get("recent_tasks") or [])
    stale_count = int(audit_summary.get("stale") or 0)
    quality_issue_count = sum(
        int(audit_summary.get(key) or 0)
        for key in ("unknown_evidence", "missing_topic", "short_note", "duplicate_file_topic")
    )

    checklist: list[dict[str, Any]] = []
    checklist.append(
        {
            "id": "review_git_status",
            "status": "needed" if status_count else "clean",
            "title": "Review Git status",
            "reason": (
                f"{status_count} Git status entries need review before handoff."
                if status_count
                else "Working tree is clean according to indexed session metadata."
            ),
            "command": "git status --short",
        }
    )
    checklist.append(
        {
            "id": "refresh_stale_memory",
            "status": "needed" if stale_count else "clean",
            "title": "Refresh stale memory",
            "reason": (
                f"{stale_count} memory notes are stale and should be refreshed or ignored."
                if stale_count
                else "No stale memory notes were found."
            ),
            "command": "init-agent tool repo_memory_list --stale --json",
        }
    )
    checklist.append(
        {
            "id": "audit_memory_quality",
            "status": "needed" if quality_issue_count else "clean",
            "title": "Audit memory quality",
            "reason": (
                f"{quality_issue_count} non-stale memory quality issues were reported."
                if quality_issue_count
                else "No memory quality issues were reported."
            ),
            "command": "init-agent tool repo_memory_audit --json",
        }
    )
    checklist.append(
        {
            "id": "review_open_tasks",
            "status": "needed" if task_count else "clean",
            "title": "Review open local tasks",
            "reason": (
                f"{task_count} local task/session items remain open."
                if task_count
                else "No open local task/session items were found."
            ),
            "command": "init-agent tool repo_task_list --json",
        }
    )
    checklist.append(
        {
            "id": "record_durable_learning",
            "status": "optional",
            "title": "Record durable learning",
            "reason": "If this session verified stable file behavior, add or update concise memory and feedback notes.",
            "command": "init-agent tool repo_memory_add --path <path> --topic <topic> --evidence read_excerpt --note <note> --json",
        }
    )
    checklist.append(
        {
            "id": "report_verification",
            "status": "manual",
            "title": "Report verification",
            "reason": "Summarize tests, smoke checks or commands run outside init-agent before ending the user-facing session.",
            "command": "",
        }
    )

    return {
        "tool": "repo_session_close",
        "contract": TOOL_CONTRACT_VERSION,
        "project": summary.get("project", {}),
        "git": git,
        "memory_audit": summary.get("memory_audit", {}),
        "recent_memory": summary.get("recent_memory", []),
        "recent_feedback": summary.get("recent_feedback", []),
        "recent_tasks": summary.get("recent_tasks", []),
        "checklist": checklist,
        "close_ready": status_count == 0 and stale_count == 0 and quality_issue_count == 0 and task_count == 0,
        "followup_commands": summary.get("followup_commands", []),
        "warnings": summary.get("warnings", []),
        "safety": [
            "session close is advisory; it does not modify source files or create commits",
            "verify files and tests directly before relying on the handoff",
            "do not commit .agent or generated local index files",
        ],
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


def _project_summary(root: Path) -> dict[str, Any]:
    git_is_available = git_available(root)
    last_map = None
    database = db_path(root)
    if database.is_file():
        try:
            with GraphStore(root) as store:
                store.initialize()
                last_map = store.latest_map_time()
        except (OSError, sqlite3.Error):
            last_map = None
    return {
        "name": root.name,
        "root": str(root),
        "git": git_is_available,
        "branch": current_branch(root) if git_is_available else None,
        "last_map": last_map,
    }


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


def _compact_feedback(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "query": item.get("query", ""),
        "path": item.get("path", ""),
        "rating": item.get("rating", ""),
        "reason": item.get("reason", ""),
        "source": item.get("source", "agent"),
        "created_at": item.get("created_at", ""),
    }


def _compact_task(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "title": item.get("title", ""),
        "status": item.get("status", ""),
        "topic": item.get("topic", ""),
        "summary": item.get("summary", ""),
        "files": list(item.get("files") or [])[:10],
        "memory_ids": list(item.get("memory_ids") or [])[:20],
        "feedback_ids": list(item.get("feedback_ids") or [])[:20],
        "tests": list(item.get("tests") or [])[:10],
        "remaining": list(item.get("remaining") or [])[:10],
        "source": item.get("source", "agent"),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
        "closed_at": item.get("closed_at", ""),
    }


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


def render_repo_graph_search_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_graph_search",
        "",
        f"Query: {result['query']}",
        "",
        "Candidate files:",
    ]
    if not result["candidate_files"]:
        lines.append("-")
    for index, item in enumerate(result["candidate_files"], start=1):
        lines.append(f"{index}. {item['path']} score {item['score']:.2f}")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"   - {reason}")
    confidence = result.get("confidence", {})
    lines.extend(["", "Confidence:", f"- Level: {confidence.get('level', '-')}"])
    for reason in confidence.get("reasons", [])[:5]:
        lines.append(f"- {reason}")
    lines.extend(["", "Next agent actions:"])
    if not result.get("next_agent_actions"):
        lines.append("-")
    for action in result.get("next_agent_actions", []):
        lines.append(f"- {action.get('command', '-')}")
        if action.get("reason"):
            lines.append(f"  reason: {action['reason']}")
    lines.extend(["", "Symbols:"])
    if not result["symbols"]:
        lines.append("-")
    for symbol in result["symbols"]:
        lines.append(f"- {symbol['name']} {symbol['kind']} in {symbol['file']}:{symbol['line']}")
    lines.extend(["", "Follow-up commands:"])
    if not result["followup_commands"]:
        lines.append("-")
    for command in result["followup_commands"]:
        lines.append(f"- {command['command']}")
    if result["warnings"]:
        lines.extend(["", "Warnings:"])
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_repo_trace_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_trace",
        "",
        f"Query: {result['query']}",
        f"Profile: {result.get('profile') or '-'}",
        "",
        "Starts:",
    ]
    if not result.get("starts"):
        lines.append("-")
    for item in result.get("starts", [])[:8]:
        lines.append(f"- {item.get('path', '-')} ({item.get('language') or '-'} / {item.get('role') or '-'})")
    lines.extend(["", "Investigation paths:"])
    if not result.get("paths"):
        lines.append("-")
    for index, item in enumerate(result.get("paths", [])[:10], start=1):
        lines.append(f"{index}. {item['target']} score {item['score']:.2f}")
        path = " -> ".join(item.get("path", []))
        if path:
            lines.append(f"   path: {path}")
        edges = " -> ".join(item.get("edges", []))
        if edges:
            lines.append(f"   edges: {edges}")
        for reason in item.get("reasons", [])[:4]:
            lines.append(f"   - {reason}")
    lines.extend(["", "Suggested first reads:"])
    if not result.get("suggested_first_reads"):
        lines.append("-")
    for path in result.get("suggested_first_reads", [])[:5]:
        lines.append(f"- {path}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result.get("followup_commands", []))
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_reading_plan_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_reading_plan",
        "",
        f"Query: {result['query']}",
        "",
        "Reading plan:",
    ]
    if not result.get("plan_items"):
        lines.append("-")
    for item in result.get("plan_items", [])[:10]:
        lines.append(f"{item['rank']}. {item['path']} score {item['score']:.2f}")
        lines.append(f"   action: {item.get('action', '-')}")
        lines.append(f"   confidence: {item.get('confidence', '-')}")
        sources = ", ".join(item.get("sources") or [])
        lines.append(f"   sources: {sources or '-'}")
        tags = ", ".join(item.get("tags") or [])
        if tags:
            lines.append(f"   tags: {tags}")
        if item.get("reason"):
            lines.append(f"   reason: {item['reason']}")
        for note in item.get("memory", [])[:2]:
            stale = "stale" if note.get("stale") else "fresh"
            if note.get("stale") is None:
                stale = "repo/unknown"
            lines.append(f"   memory #{note['id']} ({stale}): {note.get('topic') or '-'}")
    lines.extend(["", "Recommended actions:"])
    _append_commands(lines, result.get("recommended_actions", []))
    if result.get("repo_memory_context"):
        lines.extend(["", "Repo memory context:"])
        for note in result["repo_memory_context"][:5]:
            lines.append(f"- #{note['id']} {note.get('topic') or '-'}: {note.get('note') or '-'}")
    _append_warnings(lines, result.get("warnings", []))
    return "\n".join(lines)


def render_repo_related_file_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_related_file",
        "",
        f"Path: {result['path']}",
        "",
        "File:",
    ]
    if result["file"]:
        file_item = result["file"]
        lines.append(f"- {file_item['path']} ({file_item.get('language') or '-'} / {file_item.get('role') or '-'})")
    else:
        lines.append("-")
    lines.extend(["", "Symbols:"])
    if not result["symbols"]:
        lines.append("-")
    for symbol in result["symbols"][:10]:
        lines.append(f"- {symbol['kind']} {symbol['name']}:{symbol['line']}")
    lines.extend(["", "Calls:"])
    _append_calls(lines, result["calls"][:10])
    lines.extend(["", "Called by:"])
    if not result["called_by"]:
        lines.append("-")
    for caller in result["called_by"][:10]:
        first_line = caller.get("first_line") or "-"
        lines.append(f"- {caller['path']}:{first_line} calls {caller['name']} ({caller['call_count']}x)")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_symbol_callers_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_symbol_callers",
        "",
        f"Symbol: {result['symbol']}",
        "",
        "Definitions:",
    ]
    if not result["definitions"]:
        lines.append("-")
    for definition in result["definitions"]:
        lines.append(f"- {definition['kind']} {definition['path']}:{definition['line']} ({definition['language']})")
    lines.extend(["", "Callers:"])
    if not result["callers"]:
        lines.append("-")
    for caller in result["callers"][:20]:
        first_line = caller.get("first_line") or "-"
        lines.append(f"- {caller['path']}:{first_line} calls {result['symbol']} ({caller['call_count']}x)")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_overview_text(result: dict[str, Any]) -> str:
    project = result["project"]
    lines = [
        "Init Agent Tool: repo_overview",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if project.get('git') else 'no'}",
        f"Branch: {project.get('branch') or '-'}",
        "",
        "Suggested first reads:",
    ]
    if not result["suggested_first_reads"]:
        lines.append("-")
    for index, item in enumerate(result["suggested_first_reads"], start=1):
        lines.append(f"{index}. {item['path']}")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"   - {reason}")
    lines.extend(["", "Likely entry points:"])
    if not result["entry_points"]:
        lines.append("-")
    for item in result["entry_points"]:
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"- {item['path']}{detail} {item['kind']} {item['name']}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_entrypoints_text(result: dict[str, Any]) -> str:
    project = result["project"]
    lines = [
        "Init Agent Tool: repo_entrypoints",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        "",
        "Likely entry points:",
    ]
    if not result["entry_points"]:
        lines.append("-")
    for index, item in enumerate(result["entry_points"], start=1):
        detail = f":{item['line']}" if item.get("line") else ""
        lines.append(f"{index}. {item['path']}{detail} {item['kind']} {item['name']}")
    lines.extend(["", "Supporting files:"])
    if not result["supporting_files"]:
        lines.append("-")
    for item in result["supporting_files"]:
        lines.append(f"- {item['path']} ({item.get('role') or '-'} / {item.get('language') or '-'})")
        for reason in item.get("reasons", [])[:3]:
            lines.append(f"  - {reason}")
    lines.extend(["", "Manifests and config:"])
    if not result["manifests"]:
        lines.append("-")
    for item in result["manifests"]:
        lines.append(f"- {item['path']}")
    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result["followup_commands"])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_feedback_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_feedback_add",
        "",
        f"Query: {result['query']}",
        f"Path: {result['path']}",
        f"Rating: {result['rating']}",
        f"Source: {result['source']}",
        f"Recorded: {'yes' if result['recorded'] else 'no'}",
    ]
    if result.get("feedback"):
        lines.append(f"Feedback id: {result['feedback']['id']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_feedback_explain_text(result: dict[str, Any]) -> str:
    feedback = result["feedback"]
    lines = [
        "Init Agent Tool: repo_feedback_explain",
        "",
        f"Query: {feedback['query']}",
        f"Query tokens: {', '.join(feedback['query_tokens']) if feedback['query_tokens'] else '-'}",
        "",
        "Matched signals:",
    ]
    if not feedback["signals"]:
        lines.append("-")
    for signal in feedback["signals"]:
        lines.append(f"- {signal['path']} net {signal['net']:+.2f}")
        for item in signal.get("items", [])[:3]:
            lines.append(f"  - #{item['id']} {item['rating']} similarity {item['similarity']:.2f}")
            if item.get("reason"):
                lines.append(f"    reason: {item['reason']}")
    if feedback.get("ignored"):
        lines.extend(["", "Ignored feedback:"])
        for item in feedback["ignored"][:5]:
            lines.append(f"- #{item['id']} {item['rating']} {item['path']} ({item['ignored_reason']})")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_add",
        "",
        f"Scope: {result['scope']}",
        f"Path: {result['path']}",
        f"Topic: {result['topic'] or '-'}",
        f"Query: {result['query'] or '-'}",
        f"Source: {result['source']}",
        f"Evidence: {result['evidence']}",
        f"Tags: {', '.join(result.get('tags') or []) or '-'}",
        f"Recorded: {'yes' if result['recorded'] else 'no'}",
    ]
    if result.get("memory"):
        lines.append(f"Memory id: {result['memory']['id']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_search_text(result: dict[str, Any]) -> str:
    memory = result["memory"]
    lines = [
        "Init Agent Tool: repo_memory_search",
        "",
        f"Query: {memory['query']}",
        "Matches:",
    ]
    if not memory["matches"]:
        lines.append("-")
    for item in memory["matches"]:
        label = item["path"] or "(repo)"
        lines.append(f"- {label} score {item['score']:.2f}")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("tags"):
            lines.append(f"  tags: {', '.join(item['tags'])}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_file_notes_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_file_notes",
        "",
        f"Path: {result['path']}",
        "Notes:",
    ]
    if not result["notes"]:
        lines.append("-")
    for item in result["notes"]:
        lines.append(f"- #{item['id']} {item['created_at']}")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_list_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_list",
        "",
        f"Path: {result.get('path') or '-'}",
        f"Topic: {result.get('topic') or '-'}",
        f"Scope: {result.get('scope') or '-'}",
        f"Stale only: {'yes' if result.get('stale_only') else 'no'}",
        "Notes:",
    ]
    if not result["notes"]:
        lines.append("-")
    for item in result["notes"]:
        label = item["path"] or "(repo)"
        lines.append(f"- #{item['id']} {label} ({item['created_at']})")
        if item.get("scope"):
            lines.append(f"  scope: {item['scope']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("evidence"):
            lines.append(f"  evidence: {item['evidence']}")
        if item.get("stale"):
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        elif item.get("stale") is None:
            lines.append(f"  stale: unknown ({item.get('stale_reason') or 'no file hash recorded'})")
        lines.append(f"  note: {item['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_topics_text(result: dict[str, Any]) -> str:
    memory = result["memory"]
    lines = [
        "Init Agent Tool: repo_memory_topics",
        "",
        f"Topic filter: {memory.get('topic') or '-'}",
        "Topics:",
    ]
    if not memory["topics"]:
        lines.append("-")
    for item in memory["topics"]:
        label = item["topic"] or "(untitled)"
        lines.append(f"- {label}: {item['note_count']} notes, {item['file_count']} files")
        if item.get("repo_note_count"):
            lines.append(f"  repo notes: {item['repo_note_count']}")
        if item.get("stale_count"):
            lines.append(f"  stale notes: {item['stale_count']}")
        if item.get("paths"):
            lines.append(f"  paths: {', '.join(item['paths'][:5])}")
        for note in item.get("notes", [])[:3]:
            note_label = note.get("path") or "(repo)"
            lines.append(f"  - #{note['id']} {note_label}: {note['note']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_audit_text(result: dict[str, Any]) -> str:
    audit = result["audit"]
    lines = [
        "Init Agent Tool: repo_memory_audit",
        "",
        f"Notes checked: {audit.get('note_count', 0)}",
        "Summary:",
    ]
    summary = audit.get("summary") or {}
    if not summary:
        lines.append("-")
    for key, count in summary.items():
        lines.append(f"- {key}: {count}")
    issues = audit.get("issues") or {}
    for key in ("stale", "unknown_evidence", "missing_topic", "short_note"):
        items = list(issues.get(key) or [])[:5]
        if not items:
            continue
        lines.extend(["", key.replace("_", " ").title() + ":"])
        for item in items:
            label = item.get("path") or "(repo)"
            lines.append(f"- #{item['id']} {label} [{item.get('topic') or '-'}]")
    duplicates = list(issues.get("duplicate_file_topic") or [])[:5]
    if duplicates:
        lines.extend(["", "Duplicate File/Topic Groups:"])
        for item in duplicates:
            label = item.get("path") or "(repo)"
            lines.append(f"- {label} [{item.get('topic') or '-'}]: {item['note_count']} notes ids={item['ids']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_delete_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_delete",
        "",
        f"Memory id: {result['id']}",
        f"Deleted: {'yes' if result['deleted'] else 'no'}",
    ]
    if result.get("note"):
        lines.append(f"Scope: {result['note'].get('scope', 'file')}")
        lines.append(f"Path: {result['note']['path'] or '(repo)'}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_memory_update_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_memory_update",
        "",
        f"Memory id: {result['id']}",
        f"Updated: {'yes' if result['updated'] else 'no'}",
    ]
    if result.get("memory"):
        memory = result["memory"]
        lines.append(f"Scope: {memory.get('scope', 'file')}")
        lines.append(f"Path: {memory['path'] or '(repo)'}")
        if memory.get("topic"):
            lines.append(f"Topic: {memory['topic']}")
        if memory.get("evidence"):
            lines.append(f"Evidence: {memory['evidence']}")
        if memory.get("stale"):
            lines.append(f"Stale: {memory.get('stale_reason') or 'yes'}")
        elif memory.get("stale") is None:
            lines.append(f"Stale: unknown ({memory.get('stale_reason') or 'no file hash recorded'})")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_add_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_add",
        "",
        f"Recorded: {'yes' if result.get('recorded') else 'no'}",
    ]
    if result.get("task"):
        task = result["task"]
        lines.append(f"Task id: {task['id']}")
        lines.append(f"Title: {task['title']}")
        lines.append(f"Status: {task['status']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_list_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_list",
        "",
        f"Status filter: {result.get('status') or '-'}",
        f"Topic filter: {result.get('topic') or '-'}",
        "Tasks:",
    ]
    tasks = list(result.get("tasks") or [])
    if not tasks:
        lines.append("-")
    for task in tasks:
        lines.append(f"- #{task['id']} [{task['status']}] {task['title']}")
        if task.get("topic"):
            lines.append(f"  topic: {task['topic']}")
        if task.get("files"):
            lines.append(f"  files: {', '.join(task['files'][:5])}")
        if task.get("remaining"):
            lines.append(f"  remaining: {'; '.join(task['remaining'][:3])}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_update_text(result: dict[str, Any]) -> str:
    lines = [
        f"Init Agent Tool: {result['tool']}",
        "",
        f"Task id: {result['id']}",
        f"Updated: {'yes' if result.get('updated') else 'no'}",
    ]
    if result.get("task"):
        task = result["task"]
        lines.append(f"Title: {task['title']}")
        lines.append(f"Status: {task['status']}")
        if task.get("files"):
            lines.append(f"Files: {', '.join(task['files'][:5])}")
        if task.get("tests"):
            lines.append(f"Tests: {'; '.join(task['tests'][:3])}")
        if task.get("remaining"):
            lines.append(f"Remaining: {'; '.join(task['remaining'][:3])}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_task_note_text(result: dict[str, Any]) -> str:
    lines = [
        "Init Agent Tool: repo_task_note",
        "",
        f"Task id: {result['id']}",
        f"Recorded: {'yes' if result.get('recorded') else 'no'}",
    ]
    if result.get("note"):
        lines.append(f"Note id: {result['note']['id']}")
    if result.get("task"):
        lines.append(f"Status: {result['task']['status']}")
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_session_summary_text(result: dict[str, Any]) -> str:
    project = result.get("project") or {}
    git = result.get("git") or {}
    lines = [
        "Init Agent Tool: repo_session_summary",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if git.get('available') else 'no'}",
        f"Branch: {git.get('branch') or '-'}",
        "",
        "Git status:",
    ]
    status = list(git.get("status") or [])
    if not status:
        lines.append("-")
    for item in status:
        lines.append(f"- {item}")

    audit_summary = (result.get("memory_audit") or {}).get("summary") or {}
    lines.extend(["", "Memory audit:"])
    if not audit_summary:
        lines.append("-")
    for key, count in audit_summary.items():
        lines.append(f"- {key}: {count}")

    lines.extend(["", "Recent memory:"])
    recent_memory = list(result.get("recent_memory") or [])
    if not recent_memory:
        lines.append("-")
    for item in recent_memory[:5]:
        label = item.get("path") or "(repo)"
        topic = item.get("topic") or "-"
        lines.append(f"- #{item['id']} {label} [{topic}]")
        if item.get("stale") is True:
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        lines.append(f"  note: {item['note']}")

    lines.extend(["", "Recent feedback:"])
    recent_feedback = list(result.get("recent_feedback") or [])
    if not recent_feedback:
        lines.append("-")
    for item in recent_feedback[:5]:
        lines.append(f"- #{item['id']} {item['rating']} {item['path']}")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")

    lines.extend(["", "Open tasks:"])
    recent_tasks = list(result.get("recent_tasks") or [])
    if not recent_tasks:
        lines.append("-")
    for item in recent_tasks[:5]:
        lines.append(f"- #{item['id']} [{item['status']}] {item['title']}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        if item.get("remaining"):
            lines.append(f"  remaining: {'; '.join(item['remaining'][:3])}")

    lines.extend(["", "Follow-up commands:"])
    _append_commands(lines, result.get("followup_commands") or [])
    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


def render_repo_session_close_text(result: dict[str, Any]) -> str:
    project = result.get("project") or {}
    git = result.get("git") or {}
    lines = [
        "Init Agent Session Close",
        "",
        f"Project: {project.get('name') or '-'}",
        f"Root: {project.get('root') or '-'}",
        f"Git: {'yes' if git.get('available') else 'no'}",
        f"Branch: {git.get('branch') or '-'}",
        f"Close ready: {'yes' if result.get('close_ready') else 'no'}",
        "",
        "Checklist:",
    ]
    for item in result.get("checklist") or []:
        command = item.get("command") or ""
        lines.append(f"- [{item.get('status', '-')}] {item.get('title', '-')}")
        if item.get("reason"):
            lines.append(f"  reason: {item['reason']}")
        if command:
            lines.append(f"  command: {command}")

    audit_summary = (result.get("memory_audit") or {}).get("summary") or {}
    lines.extend(["", "Memory audit:"])
    if not audit_summary:
        lines.append("-")
    for key, count in audit_summary.items():
        lines.append(f"- {key}: {count}")

    status = list(git.get("status") or [])
    lines.extend(["", "Git status:"])
    if not status:
        lines.append("-")
    for item in status:
        lines.append(f"- {item}")

    lines.extend(["", "Recent memory:"])
    recent_memory = list(result.get("recent_memory") or [])
    if not recent_memory:
        lines.append("-")
    for item in recent_memory[:5]:
        label = item.get("path") or "(repo)"
        topic = item.get("topic") or "-"
        lines.append(f"- #{item['id']} {label} [{topic}]")
        if item.get("stale") is True:
            lines.append(f"  stale: {item.get('stale_reason') or 'yes'}")
        lines.append(f"  note: {item['note']}")

    lines.extend(["", "Open tasks:"])
    recent_tasks = list(result.get("recent_tasks") or [])
    if not recent_tasks:
        lines.append("-")
    for item in recent_tasks[:5]:
        lines.append(f"- #{item['id']} [{item['status']}] {item['title']}")
        if item.get("remaining"):
            lines.append(f"  remaining: {'; '.join(item['remaining'][:3])}")

    _append_warnings(lines, result["warnings"])
    return "\n".join(lines)


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


def _append_calls(lines: list[str], calls: list[dict[str, Any]]) -> None:
    printed = 0
    unresolved = 0
    for call in calls:
        definitions = call.get("definitions", [])
        if definitions:
            for definition in definitions:
                lines.append(f"- {call['name']} -> {definition['path']}:{definition['line']} ({definition['kind']})")
                printed += 1
        else:
            unresolved += 1
    if unresolved:
        lines.append(f"- {unresolved} unresolved calls omitted")
    if not printed and not unresolved:
        lines.append("-")


def _append_commands(lines: list[str], commands: list[dict[str, str]]) -> None:
    if not commands:
        lines.append("-")
    for command in commands:
        lines.append(f"- {command['command']}")


def _append_warnings(lines: list[str], warnings: list[str]) -> None:
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings:
            lines.append(f"- {warning}")


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
