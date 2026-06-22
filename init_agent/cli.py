"""Command line interface for init-agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent_tools import (
    render_repo_graph_search_text,
    render_repo_overview_text,
    render_repo_related_file_text,
    render_repo_symbol_callers_text,
    repo_graph_search,
    repo_overview,
    repo_related_file,
    repo_symbol_callers,
)
from .context_builder import build_context_pack
from .doctor import run_doctor
from .estimate import estimate_query, render_estimate_text
from .exporter import export_graph
from .feedback import add_feedback, clear_feedback, explain_feedback, export_feedback, import_feedback, list_feedback
from .git_reader import collect_git, current_branch, git_available, has_git, status_short
from .graph_store import GraphStore
from .mcp_installer import (
    install_codex_mcp_cli,
    install_codex_mcp_config,
    uninstall_codex_mcp_cli,
    uninstall_codex_mcp_config,
)
from .mcp_server import main as mcp_main
from .overview import build_overview_pack, render_overview_markdown, render_overview_text
from .query import callers_for_symbol, related as related_query
from .query import search
from .refresh import refresh_index
from .run import render_run_markdown, render_run_text, run_query
from .scanner import INDEX_VERSION, scan_project
from .skill_installer import install_codex_skill
from .utils import config_path, ensure_agent_dir, has_project_marker, project_root, utc_now, write_json


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="init-agent", description="Build a local project orientation layer for AI CLI agents.")
    parser.add_argument("--version", action="version", version=f"init-agent {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize .agent and the SQLite graph database.")
    init_parser.set_defaults(handler=cmd_init)

    map_parser = subparsers.add_parser("map", help="Scan files and build the local index.")
    map_parser.set_defaults(handler=cmd_map)

    refresh_parser = subparsers.add_parser("refresh", help="Incrementally refresh changed files in the index.")
    refresh_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    refresh_parser.set_defaults(handler=cmd_refresh)

    run_parser = subparsers.add_parser("run", help="Prepare the project and build a context pack.")
    run_parser.add_argument("text", nargs="*", help="Free-text request.")
    run_parser.add_argument("--overview", action="store_true", help="Prepare the project and print a broad repository overview.")
    run_output = run_parser.add_mutually_exclusive_group()
    run_output.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    run_output.add_argument("--markdown", action="store_true", help="Print compact Markdown.")
    run_parser.set_defaults(handler=cmd_run)

    estimate_parser = subparsers.add_parser("estimate", help="Estimate token savings for a context pack.")
    estimate_parser.add_argument("text", nargs="+", help="Free-text request.")
    estimate_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    estimate_parser.set_defaults(handler=cmd_estimate)

    overview_parser = subparsers.add_parser("overview", help="Show a broad repository orientation pack.")
    overview_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    overview_parser.add_argument("--markdown", action="store_true", help="Print compact Markdown.")
    overview_parser.set_defaults(handler=cmd_overview)

    export_parser = subparsers.add_parser("export", help="Export the indexed graph as JSON.")
    export_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    export_parser.set_defaults(handler=cmd_export)

    mcp_parser = subparsers.add_parser("mcp", help="Run or install the MCP stdio server for agent integrations.")
    mcp_parser.add_argument("--root", default=".", help="Repository root to serve. Defaults to the current directory.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_install_codex = mcp_subparsers.add_parser("install-codex", help="Register init-agent MCP with Codex using `codex mcp add`.")
    mcp_install_codex.add_argument("--root", default=".", help="Repository root to serve. Defaults to the current directory.")
    mcp_install_codex.add_argument("--server-name", default="init_agent", help="MCP server name to register.")
    mcp_install_codex.add_argument("--replace", action="store_true", help="Remove an existing Codex MCP server with the same name before adding it.")
    mcp_install_codex.add_argument("--codex-command", help="Override the codex executable path, mainly for testing.")
    mcp_install_codex.add_argument("--manual-config", action="store_true", help="Edit Codex config.toml directly instead of using `codex mcp add`.")
    mcp_install_codex.add_argument("--config-path", help="Override Codex config path. Only valid with --manual-config.")
    mcp_install_codex.add_argument("--experimental", action="store_true", help="Required only for --manual-config because direct config editing is experimental.")
    mcp_install_codex.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    mcp_install_codex.set_defaults(handler=cmd_mcp_install_codex)
    mcp_uninstall_codex = mcp_subparsers.add_parser("uninstall-codex", help="Remove init-agent MCP from Codex using `codex mcp remove`.")
    mcp_uninstall_codex.add_argument("--server-name", default="init_agent", help="MCP server name to remove.")
    mcp_uninstall_codex.add_argument("--codex-command", help="Override the codex executable path, mainly for testing.")
    mcp_uninstall_codex.add_argument("--manual-config", action="store_true", help="Edit Codex config.toml directly instead of using `codex mcp remove`.")
    mcp_uninstall_codex.add_argument("--config-path", help="Override Codex config path. Only valid with --manual-config.")
    mcp_uninstall_codex.add_argument("--experimental", action="store_true", help="Required only for --manual-config because direct config editing is experimental.")
    mcp_uninstall_codex.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    mcp_uninstall_codex.set_defaults(handler=cmd_mcp_uninstall_codex)
    mcp_parser.set_defaults(handler=cmd_mcp)

    git_parser = subparsers.add_parser("git", help="Read Git metadata into the local index.")
    git_parser.set_defaults(handler=cmd_git)

    status_parser = subparsers.add_parser("status", help="Show project index status.")
    status_parser.set_defaults(handler=cmd_status)

    query_parser = subparsers.add_parser("query", help="Search paths, symbols, roles and commit messages.")
    query_parser.add_argument("text", nargs="+", help="Search text.")
    query_parser.set_defaults(handler=cmd_query)

    context_parser = subparsers.add_parser("context", help="Build a compact context pack for an AI agent.")
    context_parser.add_argument("text", nargs="+", help="Free-text request.")
    context_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    context_parser.set_defaults(handler=cmd_context)

    doctor_parser = subparsers.add_parser("doctor", help="Run read-only diagnostics for init-agent readiness.")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    doctor_parser.set_defaults(handler=cmd_doctor)

    related_parser = subparsers.add_parser("related", help="Show symbols, links and commits related to a file.")
    related_parser.add_argument("path", help="Project-relative file path.")
    related_parser.set_defaults(handler=cmd_related)

    callers_parser = subparsers.add_parser("callers", help="Show files that call a function or symbol name.")
    callers_parser.add_argument("symbol", help="Function or symbol name.")
    callers_parser.set_defaults(handler=cmd_callers)

    symbol_parser = subparsers.add_parser("symbol", help="Show orientation details for a function or symbol name.")
    symbol_parser.add_argument("symbol", help="Function or symbol name.")
    symbol_parser.set_defaults(handler=cmd_symbol)

    install_skill_parser = subparsers.add_parser("install-skill", help="Install bundled skill templates for coding agents.")
    install_skill_parser.add_argument("target", choices=["codex"], help="Skill target to install.")
    install_skill_parser.add_argument("--target-dir", help="Override the skills directory, mainly for testing.")
    install_skill_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    install_skill_parser.set_defaults(handler=cmd_install_skill)

    tool_parser = subparsers.add_parser("tool", help="Run agent-facing tool contracts.")
    tool_subparsers = tool_parser.add_subparsers(dest="tool_command")

    repo_graph_search_parser = tool_subparsers.add_parser("repo_graph_search", help="Search the local graph for an agent task.")
    repo_graph_search_parser.add_argument("--query", required=True, help="Free-text task or question.")
    repo_graph_search_parser.add_argument("--limit", type=int, default=10, help="Maximum candidate files to return.")
    repo_graph_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_graph_search_parser.set_defaults(handler=cmd_tool_repo_graph_search)

    repo_related_file_parser = tool_subparsers.add_parser("repo_related_file", help="Inspect one indexed file neighborhood.")
    repo_related_file_parser.add_argument("--path", required=True, help="Project-relative file path.")
    repo_related_file_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_related_file_parser.set_defaults(handler=cmd_tool_repo_related_file)

    repo_symbol_callers_parser = tool_subparsers.add_parser("repo_symbol_callers", help="Inspect symbol definitions and callers.")
    repo_symbol_callers_parser.add_argument("--symbol", required=True, help="Function, class or symbol name.")
    repo_symbol_callers_parser.add_argument("--limit", type=int, default=50, help="Maximum callers to return.")
    repo_symbol_callers_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_symbol_callers_parser.set_defaults(handler=cmd_tool_repo_symbol_callers)

    repo_overview_parser = tool_subparsers.add_parser("repo_overview", help="Return a broad repository overview contract.")
    repo_overview_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_overview_parser.set_defaults(handler=cmd_tool_repo_overview)

    feedback_parser = subparsers.add_parser("feedback", help="Manage local orientation feedback.")
    feedback_subparsers = feedback_parser.add_subparsers(dest="feedback_command")

    feedback_add = feedback_subparsers.add_parser("add", help="Record feedback for a query/file pair.")
    feedback_add.add_argument("query", help="Original or similar query.")
    feedback_add.add_argument("path", help="Project-relative file path.")
    feedback_add.add_argument("--rating", required=True, choices=["crucial", "useful", "neutral", "noisy", "missing"], help="Feedback rating.")
    feedback_add.add_argument("--reason", default="", help="Short human/agent-readable reason.")
    feedback_add.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Feedback source.")
    feedback_add.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_add.set_defaults(handler=cmd_feedback_add)

    feedback_list = feedback_subparsers.add_parser("list", help="List recorded feedback.")
    feedback_list.add_argument("--query", help="Filter by exact query.")
    feedback_list.add_argument("--path", help="Filter by project-relative path.")
    feedback_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_list.set_defaults(handler=cmd_feedback_list)

    feedback_explain = feedback_subparsers.add_parser("explain", help="Explain feedback signals for a query.")
    feedback_explain.add_argument("query", nargs="+", help="Query to explain.")
    feedback_explain.add_argument("--all", action="store_true", help="Include ignored feedback entries.")
    feedback_explain.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_explain.set_defaults(handler=cmd_feedback_explain)

    feedback_clear = feedback_subparsers.add_parser("clear", help="Clear recorded feedback.")
    feedback_clear.add_argument("--query", help="Clear feedback for an exact query.")
    feedback_clear.add_argument("--path", help="Clear feedback for a project-relative path.")
    feedback_clear.add_argument("--all", action="store_true", help="Clear all feedback.")
    feedback_clear.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_clear.set_defaults(handler=cmd_feedback_clear)

    feedback_export = feedback_subparsers.add_parser("export", help="Export feedback as JSON.")
    feedback_export.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_export.set_defaults(handler=cmd_feedback_export)

    feedback_import = feedback_subparsers.add_parser("import", help="Import feedback from a JSON file.")
    feedback_import.add_argument("path", help="JSON file to import.")
    feedback_import.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    feedback_import.set_defaults(handler=cmd_feedback_import)
    return parser


def cmd_init(args: argparse.Namespace) -> int:
    root = project_root()
    ensure_agent_dir(root)
    marker_found = has_project_marker(root)
    config = {
        "project": root.name,
        "root": str(root),
        "created_at": utc_now(),
        "git": has_git(root),
        "project_marker_found": marker_found,
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
        store.set_meta("project_marker_found", str(marker_found).lower())
        store.finish_run(run_id, "ok", {"git": has_git(root), "project_marker_found": marker_found})
        store.connection.commit()
    print(f"Initialized init-agent for {root.name}")
    print(f"Root: {root}")
    print(f"Git: {'yes' if has_git(root) else 'no'}")
    if not marker_found:
        print("Note: no common project marker was found; using the current directory as root.")
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    with GraphStore(root) as store:
        store.initialize()
        run_id = store.begin_run("map")
        try:
            summary = scan_project(root, store)
            store.finish_run(run_id, "ok", summary)
        except Exception as exc:
            store.finish_run(run_id, "error", {"error": str(exc)})
            print(f"Map failed: {exc}", file=sys.stderr)
            return 1
    print("Map complete")
    print(f"Files: {summary['files']}")
    print(f"Symbols: {summary['symbols']}")
    print(f"Relations: {summary['relations']}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    root = project_root()
    result = refresh_index(root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "OK" else 1
    print("Init Agent Refresh")
    print()
    print(f"Scanned files: {result['scanned_files']}")
    print(f"Unchanged: {result['unchanged']}")
    print(f"Added: {len(result['added'])}")
    print(f"Updated: {len(result['updated'])}")
    print(f"Removed: {len(result['removed'])}")
    print()
    _print_path_list("Added files", result["added"])
    print()
    _print_path_list("Updated files", result["updated"])
    print()
    _print_path_list("Removed files", result["removed"])
    if result["errors"]:
        print()
        print("Errors:")
        for error in result["errors"]:
            print(f"- {error}")
    if result.get("suggested_commands"):
        print()
        print("Suggested commands:")
        for command in result["suggested_commands"]:
            print(f"- {command}")
    print()
    print("Final result:")
    print(result["status"])
    return 0 if result["status"] == "OK" else 1


def cmd_run(args: argparse.Namespace) -> int:
    root = project_root()
    if not args.text and not args.overview:
        print("init-agent run requires a query, or use: init-agent run --overview", file=sys.stderr)
        return 2
    query = _text_arg(args.text) if args.text else "repository overview"
    result = run_query(root, query, overview=args.overview)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.markdown:
        print(render_run_markdown(result))
    else:
        print(render_run_text(result))
    return 1 if result["preparation"]["map"] == "failed" else 0


def cmd_overview(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    pack = build_overview_pack(root)
    if args.json:
        print(json.dumps(pack, indent=2, sort_keys=True))
    elif args.markdown:
        print(render_overview_markdown(pack))
    else:
        print(render_overview_text(pack))
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    root = project_root()
    report = estimate_query(root, _text_arg(args.text))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_estimate_text(report))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    data = export_graph(root)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0
    print("Init Agent Graph Export")
    print()
    print(f"Format: {data['format']}")
    print(f"Project: {data['project']['name']}")
    print(f"Files: {data['stats']['files']}")
    print(f"Symbols: {data['stats']['symbols']}")
    print(f"Relations: {data['stats']['relations']}")
    print(f"Git commits: {data['stats']['git_commits']}")
    print()
    print("Use --json to print the full graph export.")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    return mcp_main(["--root", args.root])


def cmd_mcp_install_codex(args: argparse.Namespace) -> int:
    if args.config_path and not args.manual_config:
        result = {
            "installed": False,
            "status": "manual_config_required",
            "message": "--config-path is only valid with --manual-config.",
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Init Agent MCP Codex Setup")
            print()
            print("Status: manual config required")
            print(result["message"])
        return 2

    if args.manual_config and not args.experimental:
        result = {
            "installed": False,
            "status": "experimental_required",
            "method": "manual_config",
            "message": "Direct Codex config.toml editing is experimental. Re-run with --manual-config --experimental, or use the default `codex mcp add` path.",
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Init Agent MCP Codex Setup")
            print()
            print("Status: experimental")
            print(result["message"])
        return 2

    try:
        if args.manual_config:
            result = install_codex_mcp_config(
                Path(args.root),
                config_path=Path(args.config_path) if args.config_path else None,
                server_name=args.server_name,
                replace=args.replace,
            )
            result["method"] = "manual_config"
        else:
            result = install_codex_mcp_cli(
                Path(args.root),
                server_name=args.server_name,
                codex_command=args.codex_command,
                replace=args.replace,
            )
    except Exception as exc:
        if args.json:
            print(json.dumps({"installed": False, "status": "error", "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"Could not install Codex MCP config: {exc}")
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] in {"installed", "replaced", "exists"} else 1

    print("Init Agent MCP Codex Setup")
    print()
    if result["installed"]:
        print(f"Status: {result['status']}")
        print(f"Method: {result.get('method', 'manual_config')}")
        if result.get("config_path"):
            print(f"Config: {result['config_path']}")
        if result.get("backup_path"):
            print(f"Backup: {result['backup_path']}")
        print(f"Server: {result['server_name']}")
        print(f"Command: {result['command']}")
        print(f"Root: {result['root']}")
        for warning in result.get("warnings", []):
            print(f"Warning: {warning}")
        print()
        print(result["message"])
    else:
        print(f"Status: {result['status']}")
        print(f"Method: {result.get('method', 'codex_cli')}")
        if result.get("config_path"):
            print(f"Config: {result['config_path']}")
        print(f"Server: {result['server_name']}")
        if result.get("command"):
            print(f"Command: {result['command']}")
        if result.get("root"):
            print(f"Root: {result['root']}")
        if result.get("stderr"):
            print(f"Error: {result['stderr'].strip()}")
        print()
        print(result["message"])
    return 0 if result["status"] in {"installed", "replaced", "exists"} else 1


def cmd_mcp_uninstall_codex(args: argparse.Namespace) -> int:
    if args.config_path and not args.manual_config:
        result = {
            "removed": False,
            "status": "manual_config_required",
            "message": "--config-path is only valid with --manual-config.",
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Init Agent MCP Codex Removal")
            print()
            print("Status: manual config required")
            print(result["message"])
        return 2

    if args.manual_config and not args.experimental:
        result = {
            "removed": False,
            "status": "experimental_required",
            "method": "manual_config",
            "message": "Direct Codex config.toml editing is experimental. Re-run with --manual-config --experimental, or use the default `codex mcp remove` path.",
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print("Init Agent MCP Codex Removal")
            print()
            print("Status: experimental")
            print(result["message"])
        return 2

    try:
        if args.manual_config:
            result = uninstall_codex_mcp_config(
                config_path=Path(args.config_path) if args.config_path else None,
                server_name=args.server_name,
            )
            result["method"] = "manual_config"
        else:
            result = uninstall_codex_mcp_cli(
                server_name=args.server_name,
                codex_command=args.codex_command,
            )
    except Exception as exc:
        if args.json:
            print(json.dumps({"removed": False, "status": "error", "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"Could not remove Codex MCP config: {exc}")
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] in {"removed", "missing_config", "missing_section"} else 1

    print("Init Agent MCP Codex Removal")
    print()
    print(f"Status: {result['status']}")
    print(f"Method: {result.get('method', 'codex_cli')}")
    if result.get("config_path"):
        print(f"Config: {result['config_path']}")
    if result.get("backup_path"):
        print(f"Backup: {result['backup_path']}")
    print(f"Server: {result['server_name']}")
    if result.get("stderr"):
        print(f"Error: {result['stderr'].strip()}")
    print()
    print(result["message"])
    return 0 if result["status"] in {"removed", "missing_config", "missing_section"} else 1


def cmd_git(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    with GraphStore(root) as store:
        store.initialize()
        run_id = store.begin_run("git")
        data = collect_git(root)
        store.set_meta("git", str(data["git"]).lower())
        store.set_meta("branch", data.get("branch") or "")
        if not data["git"]:
            store.finish_run(run_id, "ok", {"git": False})
            print("Git repository not found. Nothing to import.")
            return 0
        store.replace_git_history(data["commits"])
        store.rebuild_term_stats()
        store.finish_run(
            run_id,
            "ok",
            {"branch": data["branch"], "status_files": len(data["status"]), "commits": len(data["commits"])},
        )
    print("Git metadata imported")
    print(f"Branch: {data['branch'] or 'unknown'}")
    print(f"Status entries: {len(data['status'])}")
    print(f"Commits: {len(data['commits'])}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    git_ok = git_available(root)
    branch = current_branch(root) if git_ok else None
    status = status_short(root) if git_ok else []
    with GraphStore(root) as store:
        store.initialize()
        counts = store.counts()
        project = store.get_meta("project", root.name)
        latest_map = store.latest_map_time()
    print(f"Project: {project}")
    print(f"Root: {root}")
    print(f"Git: {'yes' if git_ok else 'no'}")
    print(f"Branch: {branch or '-'}")
    print(f"Indexed files: {counts['files']}")
    print(f"Symbols: {counts['symbols']}")
    print(f"Relations: {counts['relations']}")
    print(f"Last map update: {latest_map or '-'}")
    print(f"Git modified files: {len(status)}")
    for line in status[:20]:
        print(f"  {line}")
    if len(status) > 20:
        print(f"  ... {len(status) - 20} more")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    results = search(root, _text_arg(args.text))
    if not results:
        print("No results.")
        return 0
    for item in results:
        print(f"[{item['type']}] {item['label']}")
        print(f"  {item['detail']}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    pack = build_context_pack(root, _text_arg(args.text))
    if args.json:
        print(json.dumps(pack, indent=2, sort_keys=True))
        return 0
    print(f"Context pack for: {pack['query']}")
    print()
    print("Suggested first reads:")
    if not pack["candidate_files"]:
        print("-")
    for index, item in enumerate(pack["candidate_files"], start=1):
        print(f"{index}. {item['path']}")
        print(f"   score: {item['score']:.2f}")
        print("   reasons:")
        for reason in item["reasons"]:
            print(f"   - {reason}")
    print()
    print("Related symbols:")
    if not pack["related_symbols"]:
        print("-")
    for symbol in pack["related_symbols"]:
        print(f"- {symbol['name']} {symbol['kind']} in {symbol['file']}:{symbol['line']}")
    print()
    print("Recent related commits:")
    if not pack["recent_commits"]:
        print("-")
    for commit in pack["recent_commits"]:
        print(f"- {commit['hash'][:10]} {commit['message']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = project_root()
    report = run_doctor(root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    status_by_name = {check["name"]: check for check in report["checks"]}
    stats = report["stats"]
    print("Init Agent Doctor")
    print()
    print("Status:")
    print(f"- Agent folder: {_ok_label(status_by_name, 'agent_folder')}")
    print(f"- Database: {_ok_label(status_by_name, 'database')}")
    print(f"- Config: {_ok_label(status_by_name, 'config')}")
    git_message = status_by_name.get("git_repository", {}).get("message", "")
    git_repository = "yes" in str(git_message)
    print(f"- Git repository: {'YES' if git_repository else 'NO'}")
    git_indexed = status_by_name.get("git_indexed")
    if not git_repository:
        git_indexed_label = "N/A"
    else:
        git_indexed_label = "YES" if git_indexed and git_indexed["ok"] and "yes" in str(git_indexed["message"]) else "NO"
    print(f"- Git indexed: {git_indexed_label}")
    print()
    print("Index:")
    print(f"- Files indexed: {stats['files']}")
    print(f"- Symbols: {stats['symbols']}")
    print(f"- Relations: {stats['relations']}")
    print(f"- Git commits: {stats['git_commits']}")
    print(f"- Last map: {stats['last_map'] or '-'}")
    print()
    print("Warnings:")
    if report["warnings"]:
        for warning in report["warnings"]:
            print(f"- {warning}")
    else:
        print("-")
    print()
    print("Final result:")
    print(report["status"])
    if report["suggested_commands"]:
        print()
        print("Suggested commands:")
        for command in report["suggested_commands"]:
            print(f"- {command}")
    return 0


def cmd_related(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    data = related_query(root, args.path)
    if data is None:
        print(f"File not found in index: {Path(args.path).as_posix().lstrip('./')}")
        return 1
    print(f"File: {data['file']['path']}")
    print("Symbols:")
    for symbol in data["symbols"]:
        print(f"  {symbol['kind']} {symbol['name']}:{symbol['line']}")
    if not data["symbols"]:
        print("  -")
    print("Related:")
    for relation in data["relations"]:
        print(f"  {relation['relation']} -> {relation['target_type']}:{relation['target_id']}")
    if not data["relations"]:
        print("  -")
    print("Calls:")
    unresolved_calls = 0
    printed_calls = 0
    for call in data["resolved_calls"]:
        definitions = call["definitions"]
        if definitions:
            for definition in definitions:
                print(f"  {call['name']} -> {definition['path']}:{definition['line']} ({definition['kind']})")
                printed_calls += 1
        else:
            unresolved_calls += 1
    if unresolved_calls:
        print(f"  {unresolved_calls} unresolved calls omitted")
    if not printed_calls and not unresolved_calls:
        print("  -")
    print("Called by:")
    for caller in data["callers"]:
        first_line = caller["first_line"] or "-"
        print(f"  {caller['path']}:{first_line} calls {caller['name']} ({caller['call_count']}x)")
    if not data["callers"]:
        print("  -")
    print("Recent commits:")
    for commit in data["commits"]:
        print(f"  {commit['hash'][:10]} {commit['date']} {commit['message']}")
    if not data["commits"]:
        print("  -")
    print("Changed together:")
    for file_item in data["cochanged_files"]:
        print(f"  {file_item['path']} ({file_item['commits_together']})")
    if not data["cochanged_files"]:
        print("  -")
    return 0


def cmd_callers(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    _warn_stale_index(root)
    data = callers_for_symbol(root, args.symbol)
    print(f"Symbol: {data['symbol']}")
    print("Definitions:")
    for definition in data["definitions"]:
        print(f"  {definition['kind']} {definition['path']}:{definition['line']} ({definition['language']})")
    if not data["definitions"]:
        print("  -")
    print("Callers:")
    for caller in data["callers"]:
        first_line = caller["first_line"] or "-"
        print(f"  {caller['path']}:{first_line} calls {data['symbol']} ({caller['call_count']}x)")
    if not data["callers"]:
        print("  -")
    return 0


def cmd_symbol(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    _warn_stale_index(root)
    symbol_name = args.symbol.strip()
    data = callers_for_symbol(root, symbol_name, limit=20)
    pack = build_context_pack(root, symbol_name)

    print(f"Symbol: {data['symbol']}")
    print("Definitions:")
    for definition in data["definitions"]:
        print(f"  {definition['kind']} {definition['path']}:{definition['line']} ({definition['language']})")
    if not data["definitions"]:
        print("  -")

    print("Callers:")
    for caller in data["callers"]:
        first_line = caller["first_line"] or "-"
        print(f"  {caller['path']}:{first_line} calls {data['symbol']} ({caller['call_count']}x)")
    if not data["callers"]:
        print("  -")

    print("Candidate files:")
    for item in pack["candidate_files"]:
        print(f"  {item['path']} score {item['score']:.2f}")
        for reason in item["reasons"][:3]:
            print(f"    - {reason}")
    if not pack["candidate_files"]:
        print("  -")

    print("Recent commits:")
    for commit in pack["recent_commits"]:
        print(f"  {commit['hash'][:10]} {commit['message']}")
    if not pack["recent_commits"]:
        print("  -")
    return 0


def cmd_install_skill(args: argparse.Namespace) -> int:
    try:
        if args.target != "codex":
            print(f"Unsupported skill target: {args.target}", file=sys.stderr)
            return 2
        target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
        result = install_codex_skill(target_dir)
    except OSError as exc:
        print(f"Skill install failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Skill installed")
        print(f"- Skill: {result['skill']}")
        print(f"- Target: {result['target']}")
        print("Open a new Codex session to load the skill.")
    return 0


def cmd_tool_repo_graph_search(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_graph_search(root, args.query, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_graph_search_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_related_file(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_related_file(root, args.path)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_related_file_text(result))
    if result.get("preparation", {}).get("map") == "failed":
        return 1
    return 0 if result.get("file") else 1


def cmd_tool_repo_symbol_callers(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_symbol_callers(root, args.symbol, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_symbol_callers_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_overview(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_overview(root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_overview_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_feedback_add(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    try:
        record = add_feedback(root, args.query, args.path, args.rating, args.reason, args.source)
    except ValueError as exc:
        print(f"Feedback failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print("Feedback recorded")
        print(f"- Query: {record['query']}")
        print(f"- Path: {record['path']}")
        print(f"- Rating: {record['rating']}")
        print(f"- Source: {record['source']}")
    return 0


def cmd_feedback_list(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    items = list_feedback(root, query=args.query, path=args.path)
    if args.json:
        print(json.dumps({"feedback": items}, indent=2, sort_keys=True))
        return 0
    print("Orientation feedback")
    if not items:
        print("-")
        return 0
    for item in items:
        print(f"- #{item['id']} {item['rating']} {item['path']}")
        print(f"  query: {item['query']}")
        print(f"  source: {item['source']}")
        if item["reason"]:
            print(f"  reason: {item['reason']}")
    return 0


def cmd_feedback_explain(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    result = explain_feedback(root, _text_arg(args.query), include_all=args.all)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print(f"Feedback signals for: {result['query']}")
    print()
    print(f"Query tokens: {', '.join(result['query_tokens']) if result['query_tokens'] else '-'}")
    print(f"Minimum similarity: {result['min_similarity']:.2f}")
    print()
    print("Matched signals:")
    if not result["signals"]:
        print("-")
    for signal in result["signals"]:
        print(f"- {signal['path']}")
        print(f"  boost: {signal['boost']:+.2f}")
        print(f"  penalty: {signal['penalty']:+.2f}")
        print(f"  net: {signal['net']:+.2f}")
        for item in signal["items"][:5]:
            print(
                f"  - #{item['id']} {item['rating']} similarity {item['similarity']:.2f} "
                f"contribution {item['contribution']:+.2f}"
            )
            if item["reason"]:
                print(f"    reason: {item['reason']}")

    if args.all:
        print()
        print("Ignored feedback:")
        if not result["ignored"]:
            print("-")
        for item in result["ignored"]:
            print(f"- #{item['id']} {item['rating']} {item['path']}")
            print(
                f"  similarity: {item['similarity']:.2f}; "
                f"contribution: {item['contribution']:+.2f}; "
                f"reason: {item['ignored_reason']}"
            )
    return 0


def cmd_feedback_clear(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    try:
        deleted = clear_feedback(root, query=args.query, path=args.path, all_items=args.all)
    except ValueError as exc:
        print(f"Feedback clear failed: {exc}", file=sys.stderr)
        return 2
    result = {"deleted": deleted}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Deleted feedback entries: {deleted}")
    return 0


def cmd_feedback_export(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    print(json.dumps(export_feedback(root), indent=2, sort_keys=True))
    return 0


def cmd_feedback_import(args: argparse.Namespace) -> int:
    root = project_root()
    if not _ensure_initialized(root):
        return 1
    try:
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
        imported = import_feedback(root, payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Feedback import failed: {exc}", file=sys.stderr)
        return 1
    result = {"imported": imported}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Imported feedback entries: {imported}")
    return 0


def _ensure_initialized(root: Path) -> bool:
    if not (root / ".agent" / "graph.sqlite").exists():
        print("init-agent is not initialized here. Run: init-agent init", file=sys.stderr)
        return False
    return True


def _text_arg(value: str | list[str]) -> str:
    if isinstance(value, list):
        return " ".join(value)
    return value


def _warn_stale_index(root: Path) -> None:
    try:
        with GraphStore(root) as store:
            store.initialize()
            if store.counts()["files"] > 0 and store.get_meta("index_version") != INDEX_VERSION:
                print("Warning: index was created with an older extractor. Run: init-agent map", file=sys.stderr)
    except Exception:
        return


def _ok_label(checks: dict[str, dict[str, object]], name: str) -> str:
    check = checks.get(name)
    return "OK" if check and check["ok"] else "MISSING"


def _print_path_list(title: str, paths: list[str]) -> None:
    print(f"{title}:")
    if not paths:
        print("-")
        return
    for path in paths:
        print(f"- {path}")


if __name__ == "__main__":
    raise SystemExit(main())
