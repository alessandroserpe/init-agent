"""Agent-facing tool contracts built on top of the local graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
from .feedback import add_feedback, explain_feedback
from .memory import add_note, list_notes, search_notes
from .overview import build_overview_pack
from .query import callers_for_symbol, related
from .run import run_query


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
    path: str,
    note: str,
    topic: str = "",
    query: str = "",
    source: str = "agent",
) -> dict[str, Any]:
    """Record a local file note after an agent understands a file."""

    readiness = _readiness(root)
    warnings = list(readiness["warnings"])
    normalized_path = Path(path).as_posix().lstrip("./")
    result: dict[str, Any] = {
        "tool": "repo_memory_add",
        "contract": TOOL_CONTRACT_VERSION,
        "path": normalized_path,
        "topic": topic,
        "query": query,
        "source": source,
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
    record = add_note(root, normalized_path, note, topic=topic, query=query, source=source)
    result.update(
        {
            "path": record["path"],
            "topic": record["topic"],
            "query": record["query"],
            "source": record["source"],
            "recorded": True,
            "memory": record,
        }
    )
    return result


def repo_memory_search(root: Path, query: str, path: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Search local file notes for a task or topic."""

    readiness = _readiness(root)
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


def repo_file_notes(root: Path, path: str, limit: int = 20) -> dict[str, Any]:
    """Return local notes attached to one project file."""

    readiness = _readiness(root)
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


def _readiness(root: Path) -> dict[str, Any]:
    db_path = root / ".agent" / "graph.sqlite"
    if not db_path.is_file():
        return {"ready": False, "warnings": ["init-agent index not found. Run: init-agent run --overview --markdown"]}
    try:
        with sqlite3.connect(db_path) as conn:
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    except sqlite3.Error as exc:
        return {"ready": False, "warnings": [f"init-agent index could not be read: {exc}"]}
    if files <= 0:
        return {"ready": False, "warnings": ["init-agent index is empty. Run: init-agent run --overview --markdown"]}
    return {"ready": True, "warnings": []}


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
        f"Path: {result['path']}",
        f"Topic: {result['topic'] or '-'}",
        f"Query: {result['query'] or '-'}",
        f"Source: {result['source']}",
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
        lines.append(f"- {item['path']} score {item['score']:.2f}")
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
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
        if item.get("topic"):
            lines.append(f"  topic: {item['topic']}")
        lines.append(f"  note: {item['note']}")
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
