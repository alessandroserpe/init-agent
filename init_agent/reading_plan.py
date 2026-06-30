"""Compose graph, trace, memory, feedback and tag signals into a reading plan."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
from .feedback import feedback_signals
from .graph_store import GraphStore
from .memory import list_notes, search_notes
from .text_tokens import tokenize_query
from .trace import trace_query


def build_reading_plan(root: Path, query: str, limit: int = 10, read_budget: int = 3) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 30))
    bounded_read_budget = max(1, min(read_budget, 10))
    query_tokens = tokenize_query(query)
    context = build_context_pack(root, query)
    trace = trace_query(root, query, limit=bounded_limit, max_depth=4)
    file_tags = _file_tags(root)
    indexed_paths = set(file_tags)
    feedback = feedback_signals(root, query_tokens, indexed_paths)
    notes = list_notes(root, limit=500)
    memory_matches = search_notes(root, query, limit=20)["matches"]

    candidates: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(context.get("candidate_files", []), start=1):
        path = str(item["path"])
        entry = candidates.setdefault(path, _empty_candidate(path))
        entry["graph_rank"] = index
        entry["graph_score"] = float(item.get("score") or 0.0)
        entry["sources"].add("graph")
        entry["reasons"].extend(str(reason) for reason in item.get("reasons", [])[:3])

    for index, item in enumerate(trace.get("paths", []), start=1):
        path = str(item["target"])
        entry = candidates.setdefault(path, _empty_candidate(path))
        entry["trace_rank"] = index
        entry["trace_score"] = float(item.get("score") or 0.0)
        entry["sources"].add("trace")
        if item.get("path"):
            entry["trace_path"] = list(item.get("path") or [])
        entry["reasons"].extend(str(reason) for reason in item.get("reasons", [])[:2])

    notes_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    repo_notes = []
    for note in notes:
        if note.get("scope") == "repo":
            repo_notes.append(note)
            continue
        notes_by_path[str(note.get("path") or "")].append(note)

    for match in memory_matches:
        if match.get("scope") == "repo":
            continue
        path = str(match.get("path") or "")
        if not path:
            continue
        entry = candidates.setdefault(path, _empty_candidate(path))
        entry["sources"].add("memory")
        entry["memory_score"] = max(float(entry.get("memory_score") or 0.0), float(match.get("score") or 0.0))

    for path, signal in feedback.items():
        entry = candidates.setdefault(path, _empty_candidate(path))
        entry["sources"].add("feedback")
        entry["feedback"] = _compact_feedback_signal(signal)

    for path, tags in file_tags.items():
        tag_score = _tag_score(query_tokens, tags)
        if tag_score <= 0:
            continue
        entry = candidates.setdefault(path, _empty_candidate(path))
        entry["sources"].add("tags")
        entry["tag_score"] = tag_score

    plan_items = []
    for path, entry in candidates.items():
        path_notes = sorted(notes_by_path.get(path, []), key=lambda item: -int(item["id"]))[:3]
        tags = _combined_tags(file_tags.get(path, []), path_notes)
        score = _combined_score(entry, path_notes)
        action = _action(entry, path_notes)
        plan_items.append(
            {
                "path": path,
                "rank": 0,
                "score": round(score, 4),
                "action": action,
                "confidence": _confidence(entry, path_notes),
                "sources": sorted(entry["sources"]),
                "tags": tags,
                "memory": [_compact_memory(note) for note in path_notes],
                "feedback": entry.get("feedback", {}),
                "trace_path": entry.get("trace_path", []),
                "reason": _reason(entry, path_notes, action),
            }
        )
    plan_items.sort(key=lambda item: (-float(item["score"]), str(item["path"])))
    plan_items = plan_items[:bounded_limit]
    for index, item in enumerate(plan_items, start=1):
        item["rank"] = index
    _assign_read_priorities(plan_items, bounded_read_budget)

    return {
        "query": query,
        "query_tokens": query_tokens,
        "read_budget": bounded_read_budget,
        "plan_items": plan_items,
        "memory_matches": [_compact_memory(item) for item in memory_matches[:10]],
        "repo_memory_context": [_compact_memory(note) for note in repo_notes[:5]],
        "recommended_actions": _recommended_actions(query, plan_items),
        "warnings": [
            "reading plan is heuristic; verify files before editing",
            "stale memory is a prompt to re-read, not a source of truth",
        ],
    }


def _empty_candidate(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "sources": set(),
        "reasons": [],
        "graph_rank": None,
        "graph_score": 0.0,
        "trace_rank": None,
        "trace_score": 0.0,
        "memory_score": 0.0,
        "tag_score": 0.0,
        "feedback": {},
    }


def _file_tags(root: Path) -> dict[str, list[dict[str, Any]]]:
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            """
            SELECT f.path, t.tag, t.source, t.weight
            FROM file_tags t
            JOIN files f ON f.id = t.file_id
            ORDER BY f.path, t.weight DESC, t.tag
            """
        ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["path"])].append(
            {"tag": str(row["tag"]), "source": str(row["source"]), "weight": float(row["weight"])}
        )
    return dict(grouped)


def _tag_score(query_tokens: list[str], tags: list[dict[str, Any]]) -> float:
    if not query_tokens:
        return 0.0
    query_set = set(query_tokens)
    score = 0.0
    for item in tags:
        if str(item["tag"]) in query_set:
            score += float(item.get("weight") or 1.0)
    return min(score, 8.0)


def _combined_tags(file_tags: list[dict[str, Any]], notes: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        if tag in seen:
            return
        seen.add(tag)
        result.append(tag)

    for note in notes:
        for tag in note.get("tags") or []:
            add(str(tag))
    for item in file_tags[:12]:
        add(str(item["tag"]))
    return result[:16]


def _combined_score(entry: dict[str, Any], notes: list[dict[str, Any]]) -> float:
    score = 0.0
    score += 10.0 * float(entry.get("graph_score") or 0.0)
    score += 0.35 * float(entry.get("trace_score") or 0.0)
    score += 5.0 * float(entry.get("memory_score") or 0.0)
    score += 1.5 * float(entry.get("tag_score") or 0.0)
    feedback = entry.get("feedback") or {}
    score += float(feedback.get("boost") or 0.0) * 0.4
    score += float(feedback.get("penalty") or 0.0) * 0.8
    if any(note.get("stale") is False for note in notes):
        score += 3.0
    if any(note.get("stale") is True for note in notes):
        score += 1.0
    return score


def _action(entry: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    feedback = entry.get("feedback") or {}
    if float(feedback.get("penalty") or 0.0) < 0 and not {"graph", "trace", "memory"}.intersection(entry["sources"]):
        return "skip_unless_needed"
    if any(note.get("stale") is True for note in notes):
        return "verify_stale"
    if "trace" in entry["sources"] and "graph" not in entry["sources"]:
        return "inspect_related"
    if any(note.get("stale") is False for note in notes) and "graph" not in entry["sources"]:
        return "use_memory_context"
    return "read"


def _confidence(entry: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    source_count = len(entry["sources"])
    if source_count >= 3 or any(note.get("stale") is False for note in notes):
        return "high"
    if source_count >= 2 or notes:
        return "medium"
    return "low"


def _reason(entry: dict[str, Any], notes: list[dict[str, Any]], action: str) -> str:
    if action == "verify_stale":
        return "matching local memory exists, but the file changed since that memory was recorded"
    if action == "use_memory_context":
        return "fresh local memory matches this query; use it as orientation and read before editing"
    if action == "inspect_related":
        return "trace found this file through graph relations; inspect its neighborhood before broad reading"
    feedback = entry.get("feedback") or {}
    if float(feedback.get("penalty") or 0.0) < 0:
        return "previous feedback marked this path noisy for similar work"
    reasons = [str(reason) for reason in entry.get("reasons", []) if reason]
    return reasons[0] if reasons else "matched graph, memory, feedback or tag signals"


def _compact_memory(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(note["id"]),
        "path": note.get("path", ""),
        "scope": note.get("scope", "file"),
        "topic": note.get("topic", ""),
        "note": note.get("note", ""),
        "tags": list(note.get("tags") or []),
        "evidence": note.get("evidence", "unknown"),
        "stale": note.get("stale"),
        "stale_reason": note.get("stale_reason", ""),
        "score": note.get("score"),
    }


def _compact_feedback_signal(signal: dict[str, Any]) -> dict[str, Any]:
    items = []
    for item in list(signal.get("items") or [])[:5]:
        items.append(
            {
                "id": int(item["id"]),
                "rating": item.get("rating", ""),
                "reason": item.get("reason", ""),
                "source": item.get("source", "agent"),
            }
        )
    return {
        "boost": round(float(signal.get("boost") or 0.0), 4),
        "penalty": round(float(signal.get("penalty") or 0.0), 4),
        "items": items,
    }


def _assign_read_priorities(plan_items: list[dict[str, Any]], read_budget: int) -> None:
    read_rank = 0
    for item in plan_items:
        if item.get("action") == "skip_unless_needed":
            item["read_priority"] = "skip_unless_needed"
            item["read_budget_rank"] = None
            continue
        if read_rank < read_budget and item.get("action") in {"read", "verify_stale", "inspect_related"}:
            read_rank += 1
            item["read_priority"] = "read_now"
            item["read_budget_rank"] = read_rank
            continue
        if item.get("action") in {"read", "verify_stale", "inspect_related"}:
            item["read_priority"] = "read_if_needed"
            item["read_budget_rank"] = None
            continue
        item["read_priority"] = "context_only"
        item["read_budget_rank"] = None


def _recommended_actions(query: str, plan_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions = []
    for item in [item for item in plan_items if item.get("read_priority") == "read_now"][:5]:
        path = item["path"]
        if item["action"] == "verify_stale":
            actions.append(
                {
                    "action": "read_file",
                    "command": f"init-agent tool repo_related_file --path {path!r} --json",
                    "reason": "memory is stale; inspect the current indexed neighborhood before trusting it",
                }
            )
        elif item["action"] in {"read", "inspect_related"}:
            actions.append(
                {
                    "action": "read_file",
                    "command": f"init-agent tool repo_related_file --path {path!r} --json",
                    "reason": item["reason"],
                }
            )
    if plan_items:
        actions.append(
            {
                "action": "record_feedback_after_verification",
                "command": f"init-agent feedback add {query!r} <path> --rating useful --source agent --reason \"verified relevant\"",
                "reason": "record feedback only after reading and verifying the file role",
            }
        )
    return actions[:6]
