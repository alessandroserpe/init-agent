"""Command line interface for init-agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .context_builder import build_context_pack
from .doctor import run_doctor
from .estimate import estimate_query, render_estimate_text
from .git_reader import collect_git, current_branch, git_available, has_git, status_short
from .graph_store import GraphStore
from .overview import build_overview_pack, render_overview_markdown, render_overview_text
from .query import callers_for_symbol, related as related_query
from .query import search
from .refresh import refresh_index
from .run import render_run_markdown, render_run_text, run_query
from .scanner import INDEX_VERSION, scan_project
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
