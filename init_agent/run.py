"""Automatic preparation harness for context packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
from .git_reader import collect_git, has_git
from .graph_store import GraphStore
from .overview import build_overview_pack, render_overview_markdown, render_overview_text
from .refresh import refresh_index
from .scanner import INDEX_VERSION, scan_project
from .utils import config_path, ensure_agent_dir, has_project_marker, write_json, utc_now


def run_query(root: Path, query: str, overview: bool = False) -> dict[str, Any]:
    preparation = {
        "init": "skipped",
        "map": "skipped",
        "refresh": "skipped",
        "git": "not_available",
        "warnings": [],
    }

    if not (root / ".agent").is_dir() or not (root / ".agent" / "graph.sqlite").is_file() or not config_path(root).is_file():
        try:
            _initialize_project(root)
            preparation["init"] = "done"
        except Exception as exc:
            preparation["init"] = "failed"
            preparation["warnings"].append(f"init failed: {exc}")
            return _run_result(root, query, preparation, overview, empty=True)

    try:
        index_state = _index_state(root)
    except Exception as exc:
        preparation["map"] = "failed"
        preparation["warnings"].append(f"database check failed: {exc}")
        return _run_result(root, query, preparation, overview, empty=True)

    if index_state["files"] == 0 or not index_state["current"]:
        try:
            with GraphStore(root) as store:
                store.initialize()
                run_id = store.begin_run("map")
                summary = scan_project(root, store)
                store.finish_run(run_id, "ok", summary)
            preparation["map"] = "done"
            if index_state["files"] > 0 and not index_state["current"]:
                preparation["warnings"].append("index was rebuilt because it was created with an older extractor")
        except Exception as exc:
            preparation["map"] = "failed"
            preparation["warnings"].append(f"map failed: {exc}")
            return _run_result(root, query, preparation, overview, empty=True)
    else:
        result = refresh_index(root)
        if result["status"] == "OK":
            preparation["refresh"] = "done"
        else:
            preparation["refresh"] = "failed"
            preparation["warnings"].extend(result.get("errors", []))

    if has_git(root):
        try:
            data = collect_git(root)
            if data["git"]:
                with GraphStore(root) as store:
                    store.initialize()
                    run_id = store.begin_run("git")
                    store.set_meta("git", "true")
                    store.set_meta("branch", data.get("branch") or "")
                    store.replace_git_history(data["commits"])
                    store.rebuild_term_stats()
                    store.finish_run(
                        run_id,
                        "ok",
                        {
                            "branch": data.get("branch"),
                            "status_files": len(data.get("status", [])),
                            "commits": len(data.get("commits", [])),
                        },
                    )
                preparation["git"] = "done"
            else:
                preparation["git"] = "failed"
                preparation["warnings"].append("git repository detected but git metadata could not be read")
        except Exception as exc:
            preparation["git"] = "failed"
            preparation["warnings"].append(f"git failed: {exc}")

    return _run_result(root, query, preparation, overview, empty=preparation["map"] == "failed")


def render_run_text(result: dict[str, Any]) -> str:
    prep = result["preparation"]
    if result.get("overview_mode"):
        return _render_run_overview_text(result)
    context = result["context"]
    lines = [
        "Init Agent Run",
        "",
        "Preparing project...",
        f"- Init: {_status_label(prep['init'])}",
        f"- Map: {_status_label(prep['map'])}",
        f"- Refresh: {_status_label(prep['refresh'])}",
        f"- Git: {_status_label(prep['git'])}",
    ]
    for warning in prep["warnings"]:
        lines.append(f"- Warning: {warning}")
    lines.extend(["", f"Context pack for: {context['query']}", "", "Suggested first reads:"])
    if not context["candidate_files"]:
        lines.append("-")
    for index, item in enumerate(context["candidate_files"], start=1):
        lines.append(f"{index}. {item['path']}")
        lines.append(f"   score: {item['score']:.2f}")
        lines.append("   reasons:")
        for reason in item["reasons"]:
            lines.append(f"   - {reason}")
    lines.extend(["", "Related symbols:"])
    if not context["related_symbols"]:
        lines.append("-")
    for symbol in context["related_symbols"]:
        lines.append(f"- {symbol['name']} {symbol['kind']} in {symbol['file']}:{symbol['line']}")
    lines.extend(["", "Recent related commits:"])
    if not context["recent_commits"]:
        lines.append("-")
    for commit in context["recent_commits"]:
        suffix = ""
        if commit.get("files_truncated"):
            suffix = f" (files: {len(commit.get('files', []))} of {commit.get('total_files', 0)} shown)"
        lines.append(f"- {commit['hash'][:10]} {commit['message']}{suffix}")
    return "\n".join(lines)


def render_run_markdown(result: dict[str, Any]) -> str:
    prep = result["preparation"]
    if result.get("overview_mode"):
        return _render_run_overview_markdown(result)
    context = result["context"]
    lines = [
        "# Init Agent Context Pack",
        "",
        f"Query: {context['query']}",
        "",
        "## Preparation",
        f"- Init: {_status_label(prep['init'])}",
        f"- Map: {_status_label(prep['map'])}",
        f"- Refresh: {_status_label(prep['refresh'])}",
        f"- Git: {_status_label(prep['git'])}",
    ]
    for warning in prep["warnings"]:
        lines.append(f"- Warning: {warning}")
    lines.extend(["", "## Suggested first reads"])
    if not context["candidate_files"]:
        lines.append("-")
    for index, item in enumerate(context["candidate_files"], start=1):
        lines.append(f"{index}. `{item['path']}`")
        lines.append(f"   - score: {item['score']:.2f}")
        for reason in item["reasons"]:
            lines.append(f"   - {reason}")
    lines.extend(["", "## Related symbols"])
    if not context["related_symbols"]:
        lines.append("-")
    for symbol in context["related_symbols"]:
        lines.append(f"- `{symbol['name']}` {symbol['kind']} in `{symbol['file']}:{symbol['line']}`")
    lines.extend(["", "## Recent related commits"])
    if not context["recent_commits"]:
        lines.append("-")
    for commit in context["recent_commits"]:
        lines.append(f"- `{commit['hash'][:10]}` {commit['message']}")
        if commit.get("files_truncated"):
            lines.append(f"  - files: {len(commit.get('files', []))} of {commit.get('total_files', 0)} shown")
    lines.extend(["", "## Useful follow-up commands"])
    lines.extend(_render_handoff_commands(context))
    lines.extend(
        [
            "",
            "## Safety notes",
            "- Heuristic orientation only; verify files before editing.",
            "- No source code was sent to an LLM by init-agent.",
            "- Feedback should be recorded only after files are verified.",
        ]
    )
    return "\n".join(lines)


def _render_handoff_commands(context: dict[str, Any]) -> list[str]:
    commands = []
    seen: set[str] = set()
    for item in context.get("candidate_files", [])[:3]:
        path = str(item.get("path") or "")
        if path and path not in seen:
            seen.add(path)
            commands.append(f"- `init-agent related {path}`")
    symbol_seen: set[str] = set()
    for symbol in context.get("related_symbols", [])[:5]:
        name = str(symbol.get("name") or "")
        kind = str(symbol.get("kind") or "")
        if name and name not in symbol_seen and kind in {"function", "method", "class"}:
            symbol_seen.add(name)
            commands.append(f"- `init-agent callers {name}`")
    first_path = ""
    if context.get("candidate_files"):
        first_path = str(context["candidate_files"][0].get("path") or "")
    if first_path:
        query = _shell_double_quote(str(context.get("query") or ""))
        commands.append(
            f"- `init-agent feedback add {query} {first_path} "
            '--rating useful --source agent --reason "verified relevant"`'
        )
    return commands or ["-"]


def _shell_double_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _initialize_project(root: Path) -> None:
    ensure_agent_dir(root)
    config = {
        "project": root.name,
        "root": str(root),
        "created_at": utc_now(),
        "git": has_git(root),
        "project_marker_found": has_project_marker(root),
        "exclude_dirs": [],
        "exclude_files": [],
        "exclude_extensions": [],
    }
    if not config_path(root).exists():
        write_json(config_path(root), config)
    with GraphStore(root) as store:
        store.initialize()
        run_id = store.begin_run("init")
        store.set_meta("project", root.name)
        store.set_meta("root", str(root))
        store.set_meta("git", str(has_git(root)).lower())
        store.set_meta("created_at", config["created_at"])
        store.set_meta("project_marker_found", str(config["project_marker_found"]).lower())
        store.finish_run(run_id, "ok", {"git": has_git(root), "project_marker_found": config["project_marker_found"]})
        store.connection.commit()


def _index_state(root: Path) -> dict[str, Any]:
    with GraphStore(root) as store:
        store.initialize()
        return {
            "files": store.counts()["files"],
            "current": store.get_meta("index_version") == INDEX_VERSION,
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
        "project": {
            "name": root.name,
            "root": str(root),
            "git": has_git(root),
            "branch": None,
            "last_map": None,
        },
        "suggested_first_reads": [],
        "entry_points": [],
        "manifests": [],
        "subsystems": [],
    }


def _run_result(
    root: Path,
    query: str,
    preparation: dict[str, Any],
    overview: bool,
    empty: bool = False,
) -> dict[str, Any]:
    if overview:
        pack = _empty_overview(root) if empty else build_overview_pack(root)
        return {"query": query, "preparation": preparation, "overview_mode": True, "overview": pack}
    context = _empty_context(query) if empty else build_context_pack(root, query)
    return {"query": query, "preparation": preparation, "context": context}


def _render_preparation_lines(prep: dict[str, Any]) -> list[str]:
    lines = [
        "Preparing project...",
        f"- Init: {_status_label(prep['init'])}",
        f"- Map: {_status_label(prep['map'])}",
        f"- Refresh: {_status_label(prep['refresh'])}",
        f"- Git: {_status_label(prep['git'])}",
    ]
    for warning in prep["warnings"]:
        lines.append(f"- Warning: {warning}")
    return lines


def _render_run_overview_text(result: dict[str, Any]) -> str:
    lines = ["Init Agent Run", ""]
    lines.extend(_render_preparation_lines(result["preparation"]))
    lines.extend(["", render_overview_text(result["overview"])])
    return "\n".join(lines)


def _render_run_overview_markdown(result: dict[str, Any]) -> str:
    prep = result["preparation"]
    lines = [
        "# Init Agent Repository Overview",
        "",
        "## Preparation",
        f"- Init: {_status_label(prep['init'])}",
        f"- Map: {_status_label(prep['map'])}",
        f"- Refresh: {_status_label(prep['refresh'])}",
        f"- Git: {_status_label(prep['git'])}",
    ]
    for warning in prep["warnings"]:
        lines.append(f"- Warning: {warning}")
    overview_markdown = render_overview_markdown(result["overview"]).splitlines()
    if overview_markdown and overview_markdown[0].startswith("# "):
        overview_markdown = overview_markdown[2:]
    lines.extend(["", *overview_markdown])
    return "\n".join(lines)


def _status_label(status: str) -> str:
    labels = {
        "done": "OK",
        "skipped": "skipped",
        "failed": "failed",
        "not_available": "not available",
    }
    return labels.get(status, status)
