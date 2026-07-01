"""Session summary and handoff tool contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .contracts import TOOL_CONTRACT_VERSION
from .feedback import list_feedback
from .git_reader import current_branch, git_available, status_short
from .graph_store import GraphStore
from .memory import audit_notes, list_notes
from .plan_feedback import list_reading_plans
from .tasks import list_tasks
from .utils import db_path, ensure_agent_dir


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
    plan_activity = _recent_plan_activity(root, bounded_limit) if memory_readiness["ready"] else {
        "recent_plans": [],
        "unfinished_plans": [],
        "finished_plans": [],
        "event_count": 0,
        "read_count": 0,
        "verified_count": 0,
        "useful_count": 0,
        "noisy_count": 0,
        "missing_count": 0,
    }
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
        "plan_activity": plan_activity,
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
    unfinished_plan_count = len((summary.get("plan_activity") or {}).get("unfinished_plans") or [])
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
            "id": "finish_reading_plans",
            "status": "optional" if unfinished_plan_count else "clean",
            "title": "Finalize reading plans",
            "reason": (
                f"{unfinished_plan_count} reading plans have not been finalized."
                if unfinished_plan_count
                else "No unfinished reading plans were found."
            ),
            "command": "init-agent plan stats --json",
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

    suggested_feedback, suggested_memory = _session_suggestions(summary, summary.get("plan_activity") or {})
    return {
        "tool": "repo_session_close",
        "contract": TOOL_CONTRACT_VERSION,
        "project": summary.get("project", {}),
        "git": git,
        "memory_audit": summary.get("memory_audit", {}),
        "recent_memory": summary.get("recent_memory", []),
        "recent_feedback": summary.get("recent_feedback", []),
        "recent_tasks": summary.get("recent_tasks", []),
        "plan_activity": summary.get("plan_activity", {}),
        "suggested_feedback": suggested_feedback,
        "suggested_memory": suggested_memory,
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


def _recent_plan_activity(root: Path, limit: int) -> dict[str, Any]:
    plans = list_reading_plans(root, limit=limit)
    unfinished = [plan for plan in plans if not plan.get("finished_at")]
    finished = [plan for plan in plans if plan.get("finished_at")]
    events = [event for plan in plans for event in plan.get("events", [])]
    return {
        "recent_plans": plans,
        "unfinished_plans": unfinished,
        "finished_plans": finished,
        "event_count": len(events),
        "read_count": sum(1 for event in events if event.get("event") == "read"),
        "verified_count": sum(1 for event in events if event.get("event") == "verified"),
        "useful_count": sum(1 for event in events if event.get("event") == "useful"),
        "noisy_count": sum(1 for event in events if event.get("event") == "noisy"),
        "missing_count": sum(1 for event in events if event.get("event") == "missing"),
    }


def _session_suggestions(summary: dict[str, Any], plan_activity: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    feedback: list[dict[str, str]] = []
    memory: list[dict[str, str]] = []
    for plan in plan_activity.get("unfinished_plans", [])[:5]:
        feedback.append(
            {
                "kind": "finish_plan",
                "command": f"init-agent plan finish --id {plan['id']} --summary <summary>",
                "reason": "reading plan was created but not finalized with read/verified/useful/noisy/missing signals",
            }
        )
    for plan in plan_activity.get("finished_plans", [])[:5]:
        useful_paths = [event["path"] for event in plan.get("events", []) if event.get("event") == "useful"]
        for path in useful_paths[:3]:
            memory.append(
                {
                    "kind": "memory_for_useful_file",
                    "command": f"init-agent tool repo_memory_add --path {_shell_double_quote(path)} --topic <topic> --evidence read_excerpt --tag <tag> --note <note> --json",
                    "reason": "file was marked useful in a finalized reading plan; add memory only if stable behavior was verified",
                }
            )
    for note in summary.get("recent_memory", []):
        if note.get("stale") is True:
            memory.append(
                {
                    "kind": "refresh_stale_memory",
                    "command": f"init-agent tool repo_memory_update --id {note['id']} --evidence read_excerpt --note <updated-note> --json",
                    "reason": "recent memory is stale relative to the indexed file hash",
                }
            )
    return feedback[:8], memory[:8]



def _shell_double_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
