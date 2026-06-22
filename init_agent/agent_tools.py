"""Agent-facing tool contracts built on top of the local graph."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
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
                        f"init-agent feedback add {_shell_double_quote(query)} {first_path} "
                        '--rating useful --source agent --reason "verified relevant"'
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
