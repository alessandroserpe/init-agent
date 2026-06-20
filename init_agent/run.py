"""Automatic preparation harness for context packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .context_builder import build_context_pack
from .git_reader import collect_git, has_git
from .graph_store import GraphStore
from .refresh import refresh_index
from .scanner import INDEX_VERSION, scan_project
from .utils import config_path, ensure_agent_dir, has_project_marker, write_json, utc_now


def run_query(root: Path, query: str) -> dict[str, Any]:
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
            return {"query": query, "preparation": preparation, "context": _empty_context(query)}

    try:
        index_state = _index_state(root)
    except Exception as exc:
        preparation["map"] = "failed"
        preparation["warnings"].append(f"database check failed: {exc}")
        return {"query": query, "preparation": preparation, "context": _empty_context(query)}

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
            return {"query": query, "preparation": preparation, "context": _empty_context(query)}
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

    context = build_context_pack(root, query) if preparation["map"] != "failed" else _empty_context(query)
    return {"query": query, "preparation": preparation, "context": context}


def render_run_text(result: dict[str, Any]) -> str:
    prep = result["preparation"]
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
    return "\n".join(lines)


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


def _status_label(status: str) -> str:
    labels = {
        "done": "OK",
        "skipped": "skipped",
        "failed": "failed",
        "not_available": "not available",
    }
    return labels.get(status, status)
