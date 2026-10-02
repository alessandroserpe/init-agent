"""CLI registration and handlers for optional trajectory hooks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .trajectory_hooks import (
    codex_trajectory_hook_status,
    install_codex_trajectory_hooks,
    uninstall_codex_trajectory_hooks,
)
from .utils import safe_print as print


def register_trajectory_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "trajectory",
        help="Inspect or install optional privacy-preserving Codex trajectory hooks.",
    )
    commands = parser.add_subparsers(dest="trajectory_command")
    status = commands.add_parser("status", help="Inspect optional Codex trajectory hook installation.")
    status.add_argument("--config-path", help="Override Codex hooks.json, mainly for testing.")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_trajectory_status)

    install = commands.add_parser("install-codex", help="Install optional Codex lifecycle hooks.")
    install.add_argument("--config-path", help="Override Codex hooks.json, mainly for testing.")
    install.add_argument("--command", help="Absolute path to a trusted hook executable outside the repository; defaults to a verified installation.")
    install.add_argument("--replace", action="store_true", help="Replace existing init-agent trajectory handlers.")
    install.add_argument("--json", action="store_true")
    install.set_defaults(handler=cmd_trajectory_install_codex)

    uninstall = commands.add_parser("uninstall-codex", help="Remove init-agent Codex lifecycle hooks.")
    uninstall.add_argument("--config-path", help="Override Codex hooks.json, mainly for testing.")
    uninstall.add_argument("--json", action="store_true")
    uninstall.set_defaults(handler=cmd_trajectory_uninstall_codex)


def cmd_trajectory_status(args: argparse.Namespace) -> int:
    try:
        result = codex_trajectory_hook_status(Path(args.config_path) if args.config_path else None)
    except (OSError, ValueError) as exc:
        return _trajectory_error(args, exc)
    return _render_trajectory_setup(args, result, "Codex Trajectory Hooks")


def cmd_trajectory_install_codex(args: argparse.Namespace) -> int:
    try:
        result = install_codex_trajectory_hooks(
            Path(args.config_path) if args.config_path else None,
            command=args.command,
            replace=args.replace,
        )
    except (OSError, ValueError) as exc:
        return _trajectory_error(args, exc)
    return _render_trajectory_setup(args, result, "Codex Trajectory Hook Installation")


def cmd_trajectory_uninstall_codex(args: argparse.Namespace) -> int:
    try:
        result = uninstall_codex_trajectory_hooks(Path(args.config_path) if args.config_path else None)
    except (OSError, ValueError) as exc:
        return _trajectory_error(args, exc)
    return _render_trajectory_setup(args, result, "Codex Trajectory Hook Removal")


def _render_trajectory_setup(args: argparse.Namespace, result: dict[str, Any], title: str) -> int:
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(title)
    print()
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"Config: {result.get('config_path', '-')}")
    print(f"Events: {len(result.get('events') or [])}")
    if result.get("trusted") is None and result.get("installed"):
        print("Trust: review in Codex with /hooks")
    if result.get("backup_path"):
        print(f"Backup: {result['backup_path']}")
    if result.get("message"):
        print(result["message"])
    return 0


def _trajectory_error(args: argparse.Namespace, exc: Exception) -> int:
    if args.json:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2, sort_keys=True))
    else:
        print(f"Trajectory setup failed: {exc}")
    return 1
