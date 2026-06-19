"""Token savings estimates for context packs."""

from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .run import render_run_markdown, run_query


def estimate_query(root: Path, query: str) -> dict[str, Any]:
    run_result = run_query(root, query)
    context = run_result["context"]
    context_markdown = render_run_markdown(run_result)
    context_chars = len(context_markdown)

    suggested_paths = list(context.get("suggested_first_reads", []))
    top_candidate_paths = [item["path"] for item in context.get("candidate_files", [])[:10]]
    indexed_paths = _indexed_textual_paths(root)

    suggested_chars = _character_count(root, suggested_paths)
    top_chars = _character_count(root, top_candidate_paths)
    indexed_chars = _character_count(root, indexed_paths)

    return {
        "query": query,
        "context_pack": {
            "characters": context_chars,
            "estimated_tokens": estimate_tokens(context_chars),
        },
        "suggested_first_reads": {
            "files": suggested_paths,
            "characters": suggested_chars,
            "estimated_tokens": estimate_tokens(suggested_chars),
        },
        "top_candidates": {
            "count": len(top_candidate_paths),
            "characters": top_chars,
            "estimated_tokens": estimate_tokens(top_chars),
        },
        "indexed_project": {
            "files_count": len(indexed_paths),
            "characters": indexed_chars,
            "estimated_tokens": estimate_tokens(indexed_chars),
        },
        "estimated_savings": {
            "context_vs_full_percent": _savings_percent(context_chars, indexed_chars),
            "context_plus_reads_vs_full_percent": _savings_percent(context_chars + suggested_chars, indexed_chars),
            "context_vs_top10_percent": _savings_percent(context_chars, top_chars),
            "context_plus_reads_vs_top10_percent": _savings_percent(context_chars + suggested_chars, top_chars),
        },
    }


def render_estimate_text(report: dict[str, Any]) -> str:
    lines = [
        "Init Agent Token Estimate",
        "",
        "Query:",
        report["query"],
        "",
        "Context pack:",
        f"- Estimated tokens: {_fmt(report['context_pack']['estimated_tokens'])}",
        f"- Characters: {_fmt(report['context_pack']['characters'])}",
        "",
        "Suggested first reads:",
        f"- Files: {len(report['suggested_first_reads']['files'])}",
        f"- Estimated tokens if fully read: {_fmt(report['suggested_first_reads']['estimated_tokens'])}",
        f"- Characters: {_fmt(report['suggested_first_reads']['characters'])}",
        "",
        "Top 10 candidates:",
        f"- Estimated tokens if fully read: {_fmt(report['top_candidates']['estimated_tokens'])}",
        f"- Characters: {_fmt(report['top_candidates']['characters'])}",
        "",
        "Indexed readable project:",
        f"- Files: {_fmt(report['indexed_project']['files_count'])}",
        f"- Estimated tokens if fully read: {_fmt(report['indexed_project']['estimated_tokens'])}",
        f"- Characters: {_fmt(report['indexed_project']['characters'])}",
        "",
        "Estimated savings:",
        f"- Context pack vs full indexed project: {report['estimated_savings']['context_vs_full_percent']:.1f}%",
        f"- Context pack + suggested reads vs full indexed project: {report['estimated_savings']['context_plus_reads_vs_full_percent']:.1f}%",
        f"- Context pack vs top 10 candidates: {report['estimated_savings']['context_vs_top10_percent']:.1f}%",
    ]
    return "\n".join(lines)


def estimate_tokens(char_count: int) -> int:
    return ceil(char_count / 4)


def _indexed_textual_paths(root: Path) -> list[str]:
    if not (root / ".agent" / "graph.sqlite").exists():
        return []
    with GraphStore(root) as store:
        store.initialize()
        rows = store.connection.execute(
            """
            SELECT path, language, role
            FROM files
            WHERE role IN ('source', 'test', 'route', 'view', 'migration', 'documentation', 'config', 'unknown')
              AND language NOT IN ('unknown')
            ORDER BY path
            """
        ).fetchall()
        return [row["path"] for row in rows]


def _character_count(root: Path, paths: list[str]) -> int:
    total = 0
    seen: set[str] = set()
    for rel_path in paths:
        if rel_path in seen:
            continue
        seen.add(rel_path)
        path = root / rel_path
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        text = None
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is not None:
            total += len(text)
    return total


def _savings_percent(smaller_chars: int, baseline_chars: int) -> float:
    if baseline_chars <= 0:
        return 0.0
    return round(max(0.0, (1 - (smaller_chars / baseline_chars)) * 100), 1)


def _fmt(value: int) -> str:
    return f"{value:,}"
