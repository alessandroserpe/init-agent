"""Agent-facing tool contracts built on top of the local graph."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .run import run_query


TOOL_CONTRACT_VERSION = "init-agent.tool.v1"


def repo_graph_search(root: Path, query: str, limit: int = 10) -> dict[str, Any]:
    """Return a compact JSON contract for agent graph search."""

    bounded_limit = max(1, min(limit, 20))
    run_result = run_query(root, query, overview=False)
    context = run_result.get("context", {})
    candidate_files = list(context.get("candidate_files", []))[:bounded_limit]
    symbols = list(context.get("related_symbols", []))[:10]
    related_commits = list(context.get("recent_commits", []))[:5]
    return {
        "tool": "repo_graph_search",
        "contract": TOOL_CONTRACT_VERSION,
        "query": query,
        "preparation": run_result.get("preparation", {}),
        "candidate_files": candidate_files,
        "suggested_first_reads": [item["path"] for item in candidate_files[:5]],
        "symbols": symbols,
        "related_commits": related_commits,
        "followup_commands": _followup_commands(query, candidate_files, symbols),
        "warnings": _warnings(run_result),
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
                    "command": f"init-agent related {path}",
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
                    "command": f"init-agent callers {name}",
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
