"""Command line interface for init-agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .repo_budget import WorkBudgetExceeded, budget_scope
from . import __version__
from .agent_tools import (
    render_repo_entrypoints_text,
    render_repo_feedback_add_text,
    render_repo_feedback_explain_text,
    render_repo_file_notes_text,
    render_repo_graph_search_text,
    render_repo_memory_add_text,
    render_repo_memory_audit_text,
    render_repo_memory_delete_text,
    render_repo_memory_list_text,
    render_repo_memory_search_text,
    render_repo_memory_topics_text,
    render_repo_memory_update_text,
    render_repo_overview_text,
    render_repo_flow_topics_text,
    render_repo_reading_plan_diff_text,
    render_repo_reading_plan_finish_text,
    render_repo_reading_plan_read_text,
    render_repo_reading_plan_stats_text,
    render_repo_reading_plan_text,
    render_repo_related_file_text,
    render_repo_session_close_text,
    render_repo_session_summary_text,
    render_repo_symbol_callers_text,
    render_repo_task_add_text,
    render_repo_task_list_text,
    render_repo_task_note_text,
    render_repo_task_update_text,
    render_repo_trace_text,
    render_repo_workstream_report_text,
    render_repo_workstream_review_text,
    repo_entrypoints,
    repo_feedback_add,
    repo_feedback_explain,
    repo_file_notes,
    repo_graph_search,
    repo_memory_add,
    repo_memory_audit,
    repo_memory_delete,
    repo_memory_list,
    repo_memory_search,
    repo_memory_topics,
    repo_memory_update,
    repo_overview,
    repo_flow_topics,
    repo_reading_plan_diff,
    repo_reading_plan_finish,
    repo_reading_plan_mark,
    repo_reading_plan_read,
    repo_reading_plan_stats,
    repo_reading_plan,
    repo_related_file,
    repo_session_close,
    repo_session_summary,
    repo_symbol_callers,
    repo_task_add,
    repo_task_close,
    repo_task_list,
    repo_task_note,
    repo_task_update,
    repo_trace,
    repo_workstream_report,
    repo_workstream_review,
)
from .cli_tool_commands import register_tool_subcommands
from .context_builder import build_context_pack
from .doctor import run_doctor
from .estimate import estimate_query, render_estimate_text
from .exporter import export_graph
from .feedback import add_feedback, clear_feedback, explain_feedback, export_feedback, import_feedback, list_feedback
from .git_reader import collect_git, current_branch, git_available, has_git, status_short
from .graph_store import GraphStore
from .mcp_installer import (
    codex_mcp_status,
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
from .skill_installer import install_codex_skill, sync_codex_skill
from .cli_trajectory_commands import register_trajectory_subcommands
from .trajectory_hooks import codex_trajectory_hook_status
from .web_ui import build_web_snapshot, serve_web_ui
from .utils import config_path, ensure_agent_dir, has_project_marker, normalize_repo_path, project_root, safe_print as print, utc_now, write_json


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        if args.command == "web" and not args.snapshot_json:
            return args.handler(args)
        with budget_scope():
            return args.handler(args)
    except WorkBudgetExceeded as exc:
        result = {"status": "error", "truncated": True, "error": str(exc)}
        if getattr(args, "json", False) or getattr(args, "snapshot_json", False):
            print(json.dumps(result, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="init-agent",
        description="Build a local project orientation layer for AI CLI agents.",
        epilog=(
            "Recommended daily loop: "
            "init-agent overview; "
            "init-agent plan \"<task>\" --read 3; "
            "init-agent plan finish --id <id> ...; "
            "init-agent session close. "
            "Use init-agent web for a read-only local dashboard."
        ),
    )
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

    trace_parser = subparsers.add_parser("trace", help="Trace likely investigation paths through the local graph.")
    trace_parser.add_argument("text", nargs="+", help="Free-text task or question.")
    trace_parser.add_argument("--limit", type=int, default=10, help="Maximum traced paths to return.")
    trace_parser.add_argument("--max-depth", type=int, default=4, help="Maximum graph traversal depth.")
    trace_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    trace_parser.set_defaults(handler=cmd_trace)

    plan_parser = subparsers.add_parser("plan", help="Build a memory- and feedback-aware reading plan.")
    plan_parser.add_argument("text", nargs="+", help="Free-text task or question.")
    plan_parser.add_argument("--limit", type=int, default=10, help="Maximum plan items to return.")
    plan_parser.add_argument("--read", type=int, default=3, help="Number of plan items to mark as read_now.")
    plan_parser.add_argument("--delegate", action="store_true", help="Include optional delegated workstream advice.")
    plan_parser.add_argument("--id", type=int, help="Plan id for plan tracking operations.")
    plan_parser.add_argument("--file", action="append", default=[], help="For `plan read`: file that was opened.")
    plan_parser.add_argument("--note", default="", help="For `plan read`: optional note for opened files.")
    plan_parser.add_argument("--read-file", action="append", default=[], help="For `plan finish`: file that was read.")
    plan_parser.add_argument("--verified", action="append", default=[], help="For `plan finish`: file that was verified.")
    plan_parser.add_argument("--useful", action="append", default=[], help="For `plan finish`: file verified useful.")
    plan_parser.add_argument("--central", action="append", default=[], help="For `plan finish`: central orientation target.")
    plan_parser.add_argument("--support", action="append", default=[], help="For `plan finish`: supporting file used after orientation.")
    plan_parser.add_argument("--created", action="append", default=[], help="For `plan finish`: file created during the task.")
    plan_parser.add_argument("--verification", action="append", default=[], help="For `plan finish`: test or documentation verification file.")
    plan_parser.add_argument("--noisy", action="append", default=[], help="For `plan finish`: file verified noisy.")
    plan_parser.add_argument("--missing", action="append", default=[], help="For `plan finish`: important missing file.")
    plan_parser.add_argument("--summary", default="", help="For `plan finish`: closing summary.")
    plan_parser.add_argument("--workstream", help="For `plan report/review`: delegated workstream key.")
    plan_parser.add_argument("--agent", default="subagent", help="For `plan report`: worker identity or role name.")
    plan_parser.add_argument("--modified-file", action="append", default=[], help="For `plan report`: file modified by the worker.")
    plan_parser.add_argument("--test", action="append", default=[], help="For `plan report`: verification performed.")
    plan_parser.add_argument("--finding", action="append", default=[], help="For `plan report`: verified finding.")
    plan_parser.add_argument("--risk", action="append", default=[], help="For `plan report`: known risk.")
    plan_parser.add_argument("--remaining", action="append", default=[], help="For `plan report`: remaining work.")
    plan_parser.add_argument("--decision", choices=["accepted", "rework", "rejected"], help="For `plan review`: orchestrator decision.")
    plan_parser.add_argument(
        "--kind",
        default=None,
        choices=["real", "smoke", "experiment", "planning", "diagnostic", "docs"],
        help="Plan kind for scorecard filtering.",
    )
    plan_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Plan source.")
    plan_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    plan_parser.set_defaults(handler=cmd_plan)

    scorecard_parser = subparsers.add_parser("scorecard", help="Show local orientation scorecard metrics for reading plans.")
    scorecard_parser.add_argument("--limit", type=int, default=20, help="Maximum recent finished plans to score.")
    scorecard_parser.add_argument("--all", action="store_true", help="Include smoke, experiment, planning, diagnostic and docs plans.")
    scorecard_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    scorecard_parser.set_defaults(handler=cmd_scorecard)

    overview_parser = subparsers.add_parser("overview", help="Show a broad repository orientation pack.")
    overview_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    overview_parser.add_argument("--markdown", action="store_true", help="Print compact Markdown.")
    overview_parser.set_defaults(handler=cmd_overview)

    export_parser = subparsers.add_parser("export", help="Export the indexed graph as JSON.")
    export_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    export_parser.set_defaults(handler=cmd_export)

    web_parser = subparsers.add_parser("web", help="Serve a local read-only dashboard for agent memory and session metadata.")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    web_parser.add_argument("--port", type=int, default=0, help="Port to bind. Default: OS-assigned port (0); fixed ports reuse browser origin state.")
    web_parser.add_argument("--limit", type=int, default=25, help="Maximum rows per dashboard section.")
    web_parser.add_argument("--snapshot-json", action="store_true", help="Print the dashboard data as JSON and exit.")
    web_parser.set_defaults(handler=cmd_web)

    register_trajectory_subcommands(subparsers)

    mcp_parser = subparsers.add_parser("mcp", help="Run or install the MCP stdio server for agent integrations.")
    mcp_parser.add_argument("--root", default=".", help="Repository root to serve. Defaults to the current directory.")
    mcp_parser.add_argument("--profile", choices=("core", "full"), default="core", help="MCP tool surface. Defaults to core.")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    mcp_install_codex = mcp_subparsers.add_parser("install-codex", help="Register init-agent MCP with Codex using `codex mcp add`.")
    mcp_install_codex.add_argument("--root", help="Optional repository root to pin. Omit to use the Codex session working directory.")
    mcp_install_codex.add_argument("--profile", choices=("core", "full"), default="core", help="MCP tool surface. Defaults to core.")
    mcp_install_codex.add_argument("--server-name", default="init_agent", help="MCP server name to register.")
    mcp_install_codex.add_argument("--replace", action="store_true", help="Remove an existing Codex MCP server with the same name before adding it.")
    mcp_install_codex.add_argument("--codex-command", help="Override the codex executable path, mainly for testing.")
    mcp_install_codex.add_argument("--server-command", help="Explicit absolute path to a trusted init-agent-mcp executable outside the repository.")
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

    session_parser = subparsers.add_parser("session", help="Inspect or close an agent work session.")
    session_subparsers = session_parser.add_subparsers(dest="session_command")
    session_close_parser = session_subparsers.add_parser("close", help="Print an end-of-session handoff checklist.")
    session_close_parser.add_argument("--limit", type=int, default=10, help="Maximum recent notes, feedback and git status entries to return.")
    session_close_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    session_close_parser.set_defaults(handler=cmd_session_close)

    task_parser = subparsers.add_parser("task", help="Track local agent task/session memory.")
    task_subparsers = task_parser.add_subparsers(dest="task_command")
    task_add = task_subparsers.add_parser("add", help="Create a local task/session memory item.")
    task_add.add_argument("title", help="Short task title.")
    task_add.add_argument("--topic", default="", help="Optional functional area or topic.")
    task_add.add_argument("--summary", default="", help="Short task summary.")
    task_add.add_argument("--file", action="append", default=[], help="Project-relative file path. Can be repeated.")
    task_add.add_argument("--status", default="open", choices=["open", "in_progress", "blocked", "done"], help="Initial task status.")
    task_add.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task source.")
    task_add.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    task_add.set_defaults(handler=cmd_task_add)

    task_list = task_subparsers.add_parser("list", help="List local task/session memory items.")
    task_list.add_argument("--status", choices=["open", "in_progress", "blocked", "done"], help="Optional status filter.")
    task_list.add_argument("--topic", help="Optional exact topic filter.")
    task_list.add_argument("--include-done", action="store_true", help="Include completed tasks.")
    task_list.add_argument("--limit", type=int, default=20, help="Maximum tasks to return.")
    task_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    task_list.set_defaults(handler=cmd_task_list)

    task_note = task_subparsers.add_parser("note", help="Append a progress note to a local task.")
    task_note.add_argument("id", type=int, help="Task id.")
    task_note.add_argument("--note", required=True, help="Short progress note.")
    task_note.add_argument("--file", action="append", default=[], help="Related project-relative file. Can be repeated.")
    task_note.add_argument("--memory-id", type=int, action="append", default=[], help="Related memory id. Can be repeated.")
    task_note.add_argument("--feedback-id", type=int, action="append", default=[], help="Related feedback id. Can be repeated.")
    task_note.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    task_note.add_argument("--remaining", action="append", default=[], help="Remaining follow-up. Can be repeated.")
    task_note.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task note source.")
    task_note.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    task_note.set_defaults(handler=cmd_task_note)

    task_update = task_subparsers.add_parser("update", help="Update local task/session metadata.")
    task_update.add_argument("id", type=int, help="Task id.")
    task_update.add_argument("--status", choices=["open", "in_progress", "blocked", "done"], help="Replacement status.")
    task_update.add_argument("--topic", help="Replacement topic.")
    task_update.add_argument("--summary", help="Replacement summary.")
    task_update.add_argument("--file", action="append", default=[], help="Related project-relative file. Can be repeated.")
    task_update.add_argument("--memory-id", type=int, action="append", default=[], help="Related memory id. Can be repeated.")
    task_update.add_argument("--feedback-id", type=int, action="append", default=[], help="Related feedback id. Can be repeated.")
    task_update.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    task_update.add_argument("--remaining", action="append", default=[], help="Remaining follow-up. Can be repeated.")
    task_update.add_argument("--source", choices=["user", "agent", "benchmark"], help="Replacement source.")
    task_update.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    task_update.set_defaults(handler=cmd_task_update)

    task_close = task_subparsers.add_parser("close", help="Mark a local task/session memory item done.")
    task_close.add_argument("id", type=int, help="Task id.")
    task_close.add_argument("--summary", help="Closing summary.")
    task_close.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    task_close.add_argument("--remaining", action="append", default=[], help="Known follow-up despite closing. Can be repeated.")
    task_close.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task source.")
    task_close.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    task_close.set_defaults(handler=cmd_task_close)

    query_parser = subparsers.add_parser("query", help="Search paths, symbols, roles and commit messages.")
    query_parser.add_argument("text", nargs="+", help="Search text.")
    query_parser.set_defaults(handler=cmd_query)

    context_parser = subparsers.add_parser("context", help="Build a compact context pack for an AI agent.")
    context_parser.add_argument("text", nargs="+", help="Free-text request.")
    context_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    context_parser.set_defaults(handler=cmd_context)

    doctor_parser = subparsers.add_parser("doctor", help="Run read-only diagnostics for init-agent readiness.")
    doctor_parser.add_argument(
        "--check-updates",
        action="store_true",
        help="Explicitly check GitHub for a newer init-agent release.",
    )
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    doctor_parser.set_defaults(handler=cmd_doctor)

    sync_parser = subparsers.add_parser("sync", help="Synchronize installed Codex assets with this init-agent version.")
    sync_parser.add_argument("--target-dir", help="Override the Codex skills directory, mainly for testing.")
    sync_parser.add_argument("--config-path", help="Override Codex config.toml when checking MCP registration.")
    sync_parser.add_argument("--hooks-path", help="Override Codex hooks.json when checking trajectory hooks.")
    sync_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    sync_parser.set_defaults(handler=cmd_sync)

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

    register_tool_subcommands(tool_subparsers)

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
            store.finish_run(run_id, "warning" if summary.get("errors") else "ok", summary)
        except WorkBudgetExceeded:
            store.connection.rollback()
            raise
        except Exception as exc:
            store.finish_run(run_id, "error", {"error": str(exc)})
            print(f"Map failed: {exc}", file=sys.stderr)
            return 1
    print("Map complete")
    print(f"Files: {summary['files']}")
    print(f"Symbols: {summary['symbols']}")
    print(f"Relations: {summary['relations']}")
    for error in summary.get("errors", []):
        print(f"Skipped: {error}", file=sys.stderr)
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


def cmd_trace(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_trace(root, _text_arg(args.text), limit=args.limit, max_depth=args.max_depth)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_trace_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_plan(args: argparse.Namespace) -> int:
    root = project_root()
    mode = args.text[0].lower() if args.text else ""
    if mode == "report":
        if not args.id or not args.workstream or not args.summary:
            raise SystemExit("init-agent plan report requires --id, --workstream and --summary")
        result = repo_workstream_report(
            root,
            args.id,
            args.workstream,
            args.summary,
            agent_name=args.agent,
            files_read=args.read_file,
            files_modified=args.modified_file,
            tests=args.test,
            findings=args.finding,
            risks=args.risk,
            remaining=args.remaining,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_workstream_report_text(result))
        return 0 if result.get("updated") else 1
    if mode == "review":
        if not args.id or not args.workstream or not args.decision:
            raise SystemExit("init-agent plan review requires --id, --workstream and --decision")
        result = repo_workstream_review(root, args.id, args.workstream, args.decision, note=args.note)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_workstream_review_text(result))
        return 0 if result.get("updated") else 1
    if mode == "finish":
        if not args.id:
            raise SystemExit("init-agent plan finish requires --id")
        result = repo_reading_plan_finish(
            root,
            args.id,
            read=args.read_file,
            verified=args.verified,
            useful=args.useful,
            central=args.central,
            support=args.support,
            created=args.created,
            verification=args.verification,
            noisy=args.noisy,
            missing=args.missing,
            summary=args.summary,
            source=args.source,
            kind=args.kind,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_reading_plan_finish_text(result))
        return 0 if result.get("updated") else 1
    if mode == "mark":
        if not args.id:
            raise SystemExit("init-agent plan mark requires --id")
        if not args.kind:
            raise SystemExit("init-agent plan mark requires --kind")
        result = repo_reading_plan_mark(root, args.id, args.kind)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Init Agent Tool: repo_reading_plan_mark\n\nPlan id: {result.get('id')}\nUpdated: {'yes' if result.get('updated') else 'no'}\nKind: {result.get('kind')}")
        return 0 if result.get("updated") else 1
    if mode == "read":
        if not args.id:
            raise SystemExit("init-agent plan read requires --id")
        if not args.file:
            raise SystemExit("init-agent plan read requires --file")
        result = repo_reading_plan_read(root, args.id, args.file, note=args.note, source=args.source)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_reading_plan_read_text(result))
        return 0 if result.get("updated") else 1
    if mode == "diff":
        if not args.id:
            raise SystemExit("init-agent plan diff requires --id")
        result = repo_reading_plan_diff(root, args.id)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_reading_plan_diff_text(result))
        return 0 if result.get("found") else 1
    if mode == "stats":
        result = repo_reading_plan_stats(root)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(render_repo_reading_plan_stats_text(result))
        return 0
    result = repo_reading_plan(
        root,
        _text_arg(args.text),
        limit=args.limit,
        read_budget=args.read,
        source=args.source,
        kind=args.kind or "real",
        delegate=args.delegate,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_scorecard(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan_stats(root, limit=args.limit, include_all=args.all)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_stats_text(result))
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


def cmd_web(args: argparse.Namespace) -> int:
    root = project_root()
    if args.snapshot_json:
        print(json.dumps(build_web_snapshot(root, limit=args.limit), indent=2, sort_keys=True))
        return 0
    try:
        serve_web_ui(root, host=args.host, port=args.port, limit=args.limit)
    except (ValueError, OSError) as exc:
        print(f"Web UI failed: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    return mcp_main(["--root", args.root, "--profile", args.profile])


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
                Path(args.root) if args.root else None,
                config_path=Path(args.config_path) if args.config_path else None,
                server_name=args.server_name,
                command=args.server_command,
                replace=args.replace,
                profile=args.profile,
            )
            result["method"] = "manual_config"
        else:
            result = install_codex_mcp_cli(
                Path(args.root) if args.root else None,
                server_name=args.server_name,
                command=args.server_command,
                codex_command=args.codex_command,
                replace=args.replace,
                profile=args.profile,
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
        print(f"Profile: {result.get('profile', args.profile)}")
        if result.get("root"):
            print(f"Root: {result['root']}")
        else:
            print("Root: Codex session working directory")
        if result.get("root_mode"):
            print(f"Root mode: {result['root_mode']}")
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


def cmd_session_close(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_session_close(root, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_session_close_text(result))
    return _memory_tool_exit_code(result)


def cmd_task_add(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_task_add(
            root,
            args.title,
            topic=args.topic,
            summary=args.summary,
            files=args.file,
            status=args.status,
            source=args.source,
        )
    except ValueError as exc:
        print(f"Task add failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_add_text(result))
    return 0 if result.get("recorded") else 1


def cmd_task_list(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_task_list(root, status=args.status, topic=args.topic, include_done=args.include_done, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_list_text(result))
    return _memory_tool_exit_code(result)


def cmd_task_note(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_task_note(
            root,
            args.id,
            args.note,
            files=args.file,
            memory_ids=args.memory_id,
            feedback_ids=args.feedback_id,
            tests=args.test,
            remaining=args.remaining,
            source=args.source,
        )
    except ValueError as exc:
        print(f"Task note failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_note_text(result))
    return 0 if result.get("recorded") else 1


def cmd_task_update(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_task_update(
            root,
            args.id,
            status=args.status,
            topic=args.topic,
            summary=args.summary,
            files=args.file,
            memory_ids=args.memory_id,
            feedback_ids=args.feedback_id,
            tests=args.test,
            remaining=args.remaining,
            source=args.source,
        )
    except ValueError as exc:
        print(f"Task update failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_update_text(result))
    return 0 if result.get("updated") else 1


def cmd_task_close(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_task_close(root, args.id, summary=args.summary, tests=args.test, remaining=args.remaining, source=args.source)
    except ValueError as exc:
        print(f"Task close failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_update_text(result))
    return 0 if result.get("closed") else 1


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
    report = run_doctor(root, check_updates=args.check_updates)
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
    skill_label = report["environment"]["codex_skill"]["status"].replace("_", " ").upper()
    print(f"- Codex skill: {skill_label}")
    if "release" in report["environment"]:
        release = report["environment"]["release"]
        print(f"- Latest release: {release['latest_version'] or release['status']}")
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
        print(f"File not found in index: {normalize_repo_path(args.path)}")
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


def cmd_sync(args: argparse.Namespace) -> int:
    try:
        target_dir = Path(args.target_dir).expanduser() if args.target_dir else None
        config_path = Path(args.config_path).expanduser() if args.config_path else None
        skill = sync_codex_skill(target_dir)
        mcp = codex_mcp_status(config_path)
        trajectory = codex_trajectory_hook_status(Path(args.hooks_path).expanduser() if args.hooks_path else None)
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    result = {
        "status": "ok",
        "version": __version__,
        "skill": skill,
        "mcp": mcp,
        "trajectory": trajectory,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Init Agent Sync")
        print()
        print(f"Version: {__version__}")
        print(f"Codex skill: {skill['status']}")
        print(f"Target: {skill['target']}")
        if skill.get("backup_path"):
            print(f"Backup: {skill['backup_path']}")
        for migrated in skill.get("migrated_backups", []):
            print(f"Migrated backup: {migrated}")
        print(f"Codex MCP: {mcp['status']}")
        print(mcp["message"])
        print(f"Codex trajectory hooks: {trajectory['status']}")
        if trajectory["installed"]:
            print("Review hook trust in Codex with /hooks.")
        print()
        print("Open a new Codex session when the skill or MCP installation changed.")
    return 0


def _memory_tool_exit_code(result: dict[str, Any]) -> int:
    return 0 if not result.get("warnings") else 1


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
