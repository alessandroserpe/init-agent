"""CLI registration and handlers for agent-facing tool contracts."""

from __future__ import annotations

import argparse
import json
import sys

from .agent_tools import (
    render_repo_entrypoints_text,
    render_repo_feedback_add_text,
    render_repo_feedback_explain_text,
    render_repo_file_notes_text,
    render_repo_flow_topics_text,
    render_repo_graph_search_text,
    render_repo_memory_add_text,
    render_repo_memory_audit_text,
    render_repo_memory_delete_text,
    render_repo_memory_list_text,
    render_repo_memory_search_text,
    render_repo_memory_topics_text,
    render_repo_memory_update_text,
    render_repo_overview_text,
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
    repo_entrypoints,
    repo_feedback_add,
    repo_feedback_explain,
    repo_file_notes,
    repo_flow_topics,
    repo_graph_search,
    repo_memory_add,
    repo_memory_audit,
    repo_memory_delete,
    repo_memory_list,
    repo_memory_search,
    repo_memory_topics,
    repo_memory_update,
    repo_overview,
    repo_reading_plan,
    repo_reading_plan_diff,
    repo_reading_plan_finish,
    repo_reading_plan_read,
    repo_reading_plan_stats,
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
)
from .utils import project_root


def register_tool_subcommands(tool_subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    repo_graph_search_parser = tool_subparsers.add_parser("repo_graph_search", help="Search the local graph for an agent task.")
    repo_graph_search_parser.add_argument("--query", required=True, help="Free-text task or question.")
    repo_graph_search_parser.add_argument("--limit", type=int, default=10, help="Maximum candidate files to return.")
    repo_graph_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_graph_search_parser.set_defaults(handler=cmd_tool_repo_graph_search)

    repo_trace_parser = tool_subparsers.add_parser("repo_trace", help="Trace likely investigation paths through the local graph.")
    repo_trace_parser.add_argument("--query", required=True, help="Free-text task or question.")
    repo_trace_parser.add_argument("--limit", type=int, default=10, help="Maximum traced paths to return.")
    repo_trace_parser.add_argument("--max-depth", type=int, default=4, help="Maximum graph traversal depth.")
    repo_trace_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_trace_parser.set_defaults(handler=cmd_tool_repo_trace)

    repo_reading_plan_parser = tool_subparsers.add_parser("repo_reading_plan", help="Return a memory- and feedback-aware reading plan.")
    repo_reading_plan_parser.add_argument("--query", required=True, help="Free-text task or question.")
    repo_reading_plan_parser.add_argument("--limit", type=int, default=10, help="Maximum plan items to return.")
    repo_reading_plan_parser.add_argument("--read", type=int, default=3, help="Number of plan items to mark as read_now.")
    repo_reading_plan_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_reading_plan_parser.set_defaults(handler=cmd_tool_repo_reading_plan)

    repo_reading_plan_finish_parser = tool_subparsers.add_parser("repo_reading_plan_finish", help="Finalize a reading plan with verified file outcomes.")
    repo_reading_plan_finish_parser.add_argument("--id", type=int, required=True, help="Reading plan id.")
    repo_reading_plan_finish_parser.add_argument("--read", action="append", default=[], help="File that was read. Can be repeated.")
    repo_reading_plan_finish_parser.add_argument("--verified", action="append", default=[], help="File that was verified. Can be repeated.")
    repo_reading_plan_finish_parser.add_argument("--useful", action="append", default=[], help="File verified useful. Can be repeated.")
    repo_reading_plan_finish_parser.add_argument("--noisy", action="append", default=[], help="File verified noisy. Can be repeated.")
    repo_reading_plan_finish_parser.add_argument("--missing", action="append", default=[], help="Important missing file. Can be repeated.")
    repo_reading_plan_finish_parser.add_argument("--summary", default="", help="Short closing summary.")
    repo_reading_plan_finish_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Plan finish source.")
    repo_reading_plan_finish_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_reading_plan_finish_parser.set_defaults(handler=cmd_tool_repo_reading_plan_finish)

    repo_reading_plan_read_parser = tool_subparsers.add_parser("repo_reading_plan_read", help="Record files opened while following a reading plan.")
    repo_reading_plan_read_parser.add_argument("--id", type=int, required=True, help="Reading plan id.")
    repo_reading_plan_read_parser.add_argument("--path", action="append", default=[], help="Opened file path. Can be repeated.")
    repo_reading_plan_read_parser.add_argument("--note", default="", help="Optional note for these opened files.")
    repo_reading_plan_read_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Plan read source.")
    repo_reading_plan_read_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_reading_plan_read_parser.set_defaults(handler=cmd_tool_repo_reading_plan_read)

    repo_reading_plan_diff_parser = tool_subparsers.add_parser("repo_reading_plan_diff", help="Compare a reading plan with recorded read/outcome events.")
    repo_reading_plan_diff_parser.add_argument("--id", type=int, required=True, help="Reading plan id.")
    repo_reading_plan_diff_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_reading_plan_diff_parser.set_defaults(handler=cmd_tool_repo_reading_plan_diff)

    repo_reading_plan_stats_parser = tool_subparsers.add_parser("repo_reading_plan_stats", help="Show optional local reading-plan metrics.")
    repo_reading_plan_stats_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_reading_plan_stats_parser.set_defaults(handler=cmd_tool_repo_reading_plan_stats)

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

    repo_entrypoints_parser = tool_subparsers.add_parser("repo_entrypoints", help="Return likely repository entry points.")
    repo_entrypoints_parser.add_argument("--limit", type=int, default=12, help="Maximum entry/supporting files to return.")
    repo_entrypoints_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_entrypoints_parser.set_defaults(handler=cmd_tool_repo_entrypoints)

    repo_feedback_add_parser = tool_subparsers.add_parser("repo_feedback_add", help="Record verified local orientation feedback.")
    repo_feedback_add_parser.add_argument("--query", required=True, help="Original or similar query.")
    repo_feedback_add_parser.add_argument("--path", required=True, help="Project-relative file path.")
    repo_feedback_add_parser.add_argument("--rating", required=True, choices=["crucial", "useful", "neutral", "noisy", "missing"], help="Feedback rating.")
    repo_feedback_add_parser.add_argument("--reason", default="", help="Short factual reason. Do not include source snippets.")
    repo_feedback_add_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Feedback source.")
    repo_feedback_add_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_feedback_add_parser.set_defaults(handler=cmd_tool_repo_feedback_add)

    repo_feedback_explain_parser = tool_subparsers.add_parser("repo_feedback_explain", help="Explain local feedback signals for a query.")
    repo_feedback_explain_parser.add_argument("--query", required=True, help="Query to explain.")
    repo_feedback_explain_parser.add_argument("--all", action="store_true", help="Include ignored feedback entries.")
    repo_feedback_explain_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_feedback_explain_parser.set_defaults(handler=cmd_tool_repo_feedback_explain)

    repo_memory_add_parser = tool_subparsers.add_parser("repo_memory_add", help="Record a local agent note for a file.")
    repo_memory_add_parser.add_argument("--path", help="Project-relative file path. Required for file-scoped memory.")
    repo_memory_add_parser.add_argument("--scope", default="file", choices=["file", "repo"], help="Memory scope.")
    repo_memory_add_parser.add_argument("--note", required=True, help="Short factual note. Do not include source snippets.")
    repo_memory_add_parser.add_argument("--topic", default="", help="Optional topic for the note.")
    repo_memory_add_parser.add_argument("--query", default="", help="Optional task/query that led to the note.")
    repo_memory_add_parser.add_argument("--tag", action="append", default=[], help="Structured tag for the note. Can be repeated.")
    repo_memory_add_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Memory source.")
    repo_memory_add_parser.add_argument(
        "--evidence",
        default="read_excerpt",
        choices=[
            "read_full_file",
            "read_excerpt",
            "manifest_only",
            "inferred_from_graph",
            "user_decision",
            "implementation_note",
            "planning_note",
        ],
        help="How the note was verified.",
    )
    repo_memory_add_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_add_parser.set_defaults(handler=cmd_tool_repo_memory_add)

    repo_memory_list_parser = tool_subparsers.add_parser("repo_memory_list", help="List local agent file notes.")
    repo_memory_list_parser.add_argument("--path", help="Restrict to one project-relative file path.")
    repo_memory_list_parser.add_argument("--topic", help="Restrict to an exact topic.")
    repo_memory_list_parser.add_argument("--scope", choices=["file", "repo"], help="Restrict to a memory scope.")
    repo_memory_list_parser.add_argument("--stale", action="store_true", help="Show only stale or unknown-staleness notes.")
    repo_memory_list_parser.add_argument("--limit", type=int, default=20, help="Maximum notes to return.")
    repo_memory_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_list_parser.set_defaults(handler=cmd_tool_repo_memory_list)

    repo_memory_search_parser = tool_subparsers.add_parser("repo_memory_search", help="Search local agent file notes.")
    repo_memory_search_parser.add_argument("--query", required=True, help="Task, topic or question to search.")
    repo_memory_search_parser.add_argument("--path", help="Restrict search to one project-relative file path.")
    repo_memory_search_parser.add_argument("--limit", type=int, default=10, help="Maximum notes to return.")
    repo_memory_search_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_search_parser.set_defaults(handler=cmd_tool_repo_memory_search)

    repo_memory_topics_parser = tool_subparsers.add_parser("repo_memory_topics", help="Summarize local memory notes by topic.")
    repo_memory_topics_parser.add_argument("--topic", help="Restrict to an exact topic.")
    repo_memory_topics_parser.add_argument("--limit", type=int, default=20, help="Maximum topics to return.")
    repo_memory_topics_parser.add_argument("--notes-per-topic", type=int, default=5, help="Maximum notes to include per topic.")
    repo_memory_topics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_topics_parser.set_defaults(handler=cmd_tool_repo_memory_topics)

    repo_flow_topics_parser = tool_subparsers.add_parser("repo_flow_topics", help="Aggregate tags, topics and files into flow-oriented groups.")
    repo_flow_topics_parser.add_argument("--tag", help="Restrict to one tag.")
    repo_flow_topics_parser.add_argument("--limit", type=int, default=20, help="Maximum flows to return.")
    repo_flow_topics_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_flow_topics_parser.set_defaults(handler=cmd_tool_repo_flow_topics)

    repo_memory_audit_parser = tool_subparsers.add_parser("repo_memory_audit", help="Audit local memory note quality.")
    repo_memory_audit_parser.add_argument("--limit", type=int, default=100, help="Maximum notes to audit.")
    repo_memory_audit_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_audit_parser.set_defaults(handler=cmd_tool_repo_memory_audit)

    repo_session_summary_parser = tool_subparsers.add_parser("repo_session_summary", help="Summarize local session metadata for agent handoff.")
    repo_session_summary_parser.add_argument("--limit", type=int, default=10, help="Maximum recent notes, feedback and git status entries to return.")
    repo_session_summary_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_session_summary_parser.set_defaults(handler=cmd_tool_repo_session_summary)

    repo_session_close_parser = tool_subparsers.add_parser("repo_session_close", help="Return an end-of-session handoff checklist.")
    repo_session_close_parser.add_argument("--limit", type=int, default=10, help="Maximum recent notes, feedback and git status entries to return.")
    repo_session_close_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_session_close_parser.set_defaults(handler=cmd_tool_repo_session_close)

    repo_file_notes_parser = tool_subparsers.add_parser("repo_file_notes", help="List local agent notes for one file.")
    repo_file_notes_parser.add_argument("--path", required=True, help="Project-relative file path.")
    repo_file_notes_parser.add_argument("--limit", type=int, default=20, help="Maximum notes to return.")
    repo_file_notes_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_file_notes_parser.set_defaults(handler=cmd_tool_repo_file_notes)

    repo_memory_delete_parser = tool_subparsers.add_parser("repo_memory_delete", help="Delete one local agent file note by id.")
    repo_memory_delete_parser.add_argument("--id", type=int, required=True, help="Memory note id to delete.")
    repo_memory_delete_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_delete_parser.set_defaults(handler=cmd_tool_repo_memory_delete)

    repo_memory_update_parser = tool_subparsers.add_parser("repo_memory_update", help="Update one local agent note by id and refresh its hash.")
    repo_memory_update_parser.add_argument("--id", type=int, required=True, help="Memory note id to update.")
    repo_memory_update_parser.add_argument("--note", help="Replacement short factual note. Do not include source snippets.")
    repo_memory_update_parser.add_argument("--topic", help="Replacement topic.")
    repo_memory_update_parser.add_argument("--query", help="Replacement task/query that led to the note.")
    repo_memory_update_parser.add_argument("--tag", action="append", help="Replacement structured tag. Can be repeated.")
    repo_memory_update_parser.add_argument("--source", choices=["user", "agent", "benchmark"], help="Replacement memory source.")
    repo_memory_update_parser.add_argument(
        "--evidence",
        choices=[
            "read_full_file",
            "read_excerpt",
            "manifest_only",
            "inferred_from_graph",
            "user_decision",
            "implementation_note",
            "planning_note",
        ],
        help="Replacement evidence level.",
    )
    repo_memory_update_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_memory_update_parser.set_defaults(handler=cmd_tool_repo_memory_update)

    repo_task_add_parser = tool_subparsers.add_parser("repo_task_add", help="Create a local task/session memory item.")
    repo_task_add_parser.add_argument("--title", required=True, help="Short task title.")
    repo_task_add_parser.add_argument("--topic", default="", help="Optional functional area or topic.")
    repo_task_add_parser.add_argument("--summary", default="", help="Short task summary.")
    repo_task_add_parser.add_argument("--file", action="append", default=[], help="Related project-relative file. Can be repeated.")
    repo_task_add_parser.add_argument("--status", default="open", choices=["open", "in_progress", "blocked", "done"], help="Initial task status.")
    repo_task_add_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task source.")
    repo_task_add_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_task_add_parser.set_defaults(handler=cmd_tool_repo_task_add)

    repo_task_list_parser = tool_subparsers.add_parser("repo_task_list", help="List local task/session memory items.")
    repo_task_list_parser.add_argument("--status", choices=["open", "in_progress", "blocked", "done"], help="Optional status filter.")
    repo_task_list_parser.add_argument("--topic", help="Optional exact topic filter.")
    repo_task_list_parser.add_argument("--include-done", action="store_true", help="Include completed tasks.")
    repo_task_list_parser.add_argument("--limit", type=int, default=20, help="Maximum tasks to return.")
    repo_task_list_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_task_list_parser.set_defaults(handler=cmd_tool_repo_task_list)

    repo_task_note_parser = tool_subparsers.add_parser("repo_task_note", help="Append a progress note to a local task.")
    repo_task_note_parser.add_argument("--id", type=int, required=True, help="Task id.")
    repo_task_note_parser.add_argument("--note", required=True, help="Short progress note.")
    repo_task_note_parser.add_argument("--file", action="append", default=[], help="Related project-relative file. Can be repeated.")
    repo_task_note_parser.add_argument("--memory-id", type=int, action="append", default=[], help="Related memory id. Can be repeated.")
    repo_task_note_parser.add_argument("--feedback-id", type=int, action="append", default=[], help="Related feedback id. Can be repeated.")
    repo_task_note_parser.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    repo_task_note_parser.add_argument("--remaining", action="append", default=[], help="Remaining follow-up. Can be repeated.")
    repo_task_note_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task note source.")
    repo_task_note_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_task_note_parser.set_defaults(handler=cmd_tool_repo_task_note)

    repo_task_update_parser = tool_subparsers.add_parser("repo_task_update", help="Update local task/session metadata.")
    repo_task_update_parser.add_argument("--id", type=int, required=True, help="Task id.")
    repo_task_update_parser.add_argument("--status", choices=["open", "in_progress", "blocked", "done"], help="Replacement status.")
    repo_task_update_parser.add_argument("--topic", help="Replacement topic.")
    repo_task_update_parser.add_argument("--summary", help="Replacement summary.")
    repo_task_update_parser.add_argument("--file", action="append", default=[], help="Related project-relative file. Can be repeated.")
    repo_task_update_parser.add_argument("--memory-id", type=int, action="append", default=[], help="Related memory id. Can be repeated.")
    repo_task_update_parser.add_argument("--feedback-id", type=int, action="append", default=[], help="Related feedback id. Can be repeated.")
    repo_task_update_parser.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    repo_task_update_parser.add_argument("--remaining", action="append", default=[], help="Remaining follow-up. Can be repeated.")
    repo_task_update_parser.add_argument("--source", choices=["user", "agent", "benchmark"], help="Replacement source.")
    repo_task_update_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_task_update_parser.set_defaults(handler=cmd_tool_repo_task_update)

    repo_task_close_parser = tool_subparsers.add_parser("repo_task_close", help="Mark a local task/session memory item done.")
    repo_task_close_parser.add_argument("--id", type=int, required=True, help="Task id.")
    repo_task_close_parser.add_argument("--summary", help="Closing summary.")
    repo_task_close_parser.add_argument("--test", action="append", default=[], help="Verification performed. Can be repeated.")
    repo_task_close_parser.add_argument("--remaining", action="append", default=[], help="Known follow-up despite closing. Can be repeated.")
    repo_task_close_parser.add_argument("--source", default="agent", choices=["user", "agent", "benchmark"], help="Task source.")
    repo_task_close_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    repo_task_close_parser.set_defaults(handler=cmd_tool_repo_task_close)




def cmd_tool_repo_graph_search(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_graph_search(root, args.query, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_graph_search_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_trace(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_trace(root, args.query, limit=args.limit, max_depth=args.max_depth)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_trace_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_reading_plan(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan(root, args.query, limit=args.limit, read_budget=args.read)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_reading_plan_finish(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan_finish(
        root,
        args.id,
        read=args.read,
        verified=args.verified,
        useful=args.useful,
        noisy=args.noisy,
        missing=args.missing,
        summary=args.summary,
        source=args.source,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_finish_text(result))
    return 0 if result.get("updated") else 1


def cmd_tool_repo_reading_plan_read(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan_read(root, args.id, args.path, note=args.note, source=args.source)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_read_text(result))
    return 0 if result.get("updated") else 1


def cmd_tool_repo_reading_plan_diff(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan_diff(root, args.id)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_diff_text(result))
    return 0 if result.get("found") else 1


def cmd_tool_repo_reading_plan_stats(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_reading_plan_stats(root)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_reading_plan_stats_text(result))
    return 0


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


def cmd_tool_repo_entrypoints(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_entrypoints(root, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_entrypoints_text(result))
    return 1 if result.get("preparation", {}).get("map") == "failed" else 0


def cmd_tool_repo_feedback_add(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_feedback_add(root, args.query, args.path, args.rating, reason=args.reason, source=args.source)
    except ValueError as exc:
        print(f"Feedback failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_feedback_add_text(result))
    return 0 if result.get("recorded") else 1


def cmd_tool_repo_feedback_explain(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_feedback_explain(root, args.query, include_all=args.all)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_feedback_explain_text(result))
    return 0 if not result.get("warnings") else 1


def cmd_tool_repo_memory_add(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_memory_add(
            root,
            args.path,
            args.note,
            topic=args.topic,
            query=args.query,
            source=args.source,
            evidence=args.evidence,
            scope=args.scope,
            tags=args.tag,
        )
    except ValueError as exc:
        print(f"Memory failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_add_text(result))
    return 0 if result.get("recorded") else 1


def cmd_tool_repo_memory_list(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_memory_list(root, path=args.path, topic=args.topic, scope=args.scope, stale_only=args.stale, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_list_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_memory_search(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_memory_search(root, args.query, path=args.path, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_search_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_memory_topics(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_memory_topics(root, topic=args.topic, limit=args.limit, notes_per_topic=args.notes_per_topic)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_topics_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_flow_topics(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_flow_topics(root, tag=args.tag, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_flow_topics_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_memory_audit(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_memory_audit(root, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_audit_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_session_summary(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_session_summary(root, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_session_summary_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_session_close(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_session_close(root, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_session_close_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_file_notes(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_file_notes(root, args.path, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_file_notes_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_memory_delete(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_memory_delete(root, args.id)
    except ValueError as exc:
        print(f"Memory delete failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_delete_text(result))
    return 0 if result.get("deleted") else 1


def cmd_tool_repo_memory_update(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        result = repo_memory_update(
            root,
            args.id,
            note=args.note,
            topic=args.topic,
            query=args.query,
            source=args.source,
            evidence=args.evidence,
            tags=args.tag,
        )
    except ValueError as exc:
        print(f"Memory update failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_memory_update_text(result))
    return 0 if result.get("updated") else 1


def cmd_tool_repo_task_add(args: argparse.Namespace) -> int:
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


def cmd_tool_repo_task_list(args: argparse.Namespace) -> int:
    root = project_root()
    result = repo_task_list(root, status=args.status, topic=args.topic, include_done=args.include_done, limit=args.limit)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(render_repo_task_list_text(result))
    return _memory_tool_exit_code(result)


def cmd_tool_repo_task_note(args: argparse.Namespace) -> int:
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


def cmd_tool_repo_task_update(args: argparse.Namespace) -> int:
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


def cmd_tool_repo_task_close(args: argparse.Namespace) -> int:
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


def _memory_tool_exit_code(result: dict[str, Any]) -> int:
    warnings = [str(warning) for warning in result.get("warnings", [])]
    return 1 if any("memory store could not be read" in warning for warning in warnings) else 0


