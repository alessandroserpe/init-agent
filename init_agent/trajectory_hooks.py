"""Install and inspect optional Codex trajectory lifecycle hooks."""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .executables import resolve_executable
from .private_files import copy_private_file, harden_private_path

from .trajectory import CODEX_HOOK_EVENTS


DEFAULT_CODEX_HOOKS = Path.home() / ".codex" / "hooks.json"
HOOK_COMMAND_MARKER = "--init-agent-trajectory-hook"


def codex_trajectory_hook_status(config_path: Path | None = None) -> dict[str, Any]:
    target = (config_path or _codex_hooks_path()).expanduser()
    if not target.is_file():
        return {
            "installed": False,
            "current": False,
            "status": "missing",
            "trusted": None,
            "config_path": str(target),
            "events": [],
        }
    data = _read_hooks(target)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return {
            "installed": False,
            "current": False,
            "status": "invalid",
            "trusted": None,
            "config_path": str(target),
            "events": [],
        }
    events = sorted(event for event in CODEX_HOOK_EVENTS if _event_has_init_agent(hooks.get(event)))
    current = set(events) == CODEX_HOOK_EVENTS and all(_event_has_current_hook(hooks.get(event)) for event in events)
    return {
        "installed": bool(events),
        "current": current,
        "status": "configured" if current else ("partial" if events else "missing"),
        "trusted": None,
        "config_path": str(target),
        "events": events,
    }


def install_codex_trajectory_hooks(
    config_path: Path | None = None,
    *,
    command: str | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    resolved_command = resolve_executable("init-agent-hook", command, required=True, verify_explicit=True)
    target = (config_path or _codex_hooks_path()).expanduser()
    data = _read_hooks(target) if target.is_file() else {}
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks.json has a non-object 'hooks' field")

    before = codex_trajectory_hook_status(target)
    if before["current"] and not replace:
        return {**before, "installed": True, "updated": False, "backup_path": None}

    _remove_init_agent_handlers(hooks)
    hook_command = f"{shlex.quote(resolved_command)} {HOOK_COMMAND_MARKER}"
    for event in sorted(CODEX_HOOK_EVENTS):
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Codex hooks.json event '{event}' must contain a list")
        groups.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 3,
                    }
                ]
            }
        )

    backup = _backup_file(target) if target.is_file() else None
    _write_json_atomic(target, data)
    after = codex_trajectory_hook_status(target)
    return {
        **after,
        "installed": True,
        "updated": bool(before["installed"]),
        "backup_path": str(backup) if backup else None,
        "message": "Trajectory hooks installed. Review and trust them with /hooks, then restart Codex.",
    }


def uninstall_codex_trajectory_hooks(config_path: Path | None = None) -> dict[str, Any]:
    target = (config_path or _codex_hooks_path()).expanduser()
    before = codex_trajectory_hook_status(target)
    if not target.is_file() or not before["installed"]:
        return {
            **before,
            "removed": False,
            "backup_path": None,
            "message": "No init-agent trajectory hooks were configured.",
        }
    data = _read_hooks(target)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks.json has a non-object 'hooks' field")
    _remove_init_agent_handlers(hooks)
    backup = _backup_file(target)
    _write_json_atomic(target, data)
    return {
        "installed": False,
        "current": False,
        "status": "removed",
        "trusted": None,
        "config_path": str(target),
        "events": [],
        "removed": True,
        "backup_path": str(backup),
        "message": "Trajectory hooks removed. Restart Codex to apply the change.",
    }


def _remove_init_agent_handlers(hooks: dict[str, Any]) -> None:
    for event in list(hooks):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        remaining_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict):
                remaining_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                remaining_groups.append(group)
                continue
            remaining_handlers = [handler for handler in handlers if not _is_init_agent_handler(handler)]
            if remaining_handlers:
                remaining_groups.append({**group, "hooks": remaining_handlers})
        if remaining_groups:
            hooks[event] = remaining_groups
        else:
            hooks.pop(event, None)


def _event_has_init_agent(groups: Any) -> bool:
    if not isinstance(groups, list):
        return False
    return any(
        _is_init_agent_handler(handler)
        for group in groups
        if isinstance(group, dict)
        for handler in (group.get("hooks") or [])
    )


def _event_has_current_hook(groups: Any) -> bool:
    found = False
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for handler in group.get("hooks") or []:
            if not _is_init_agent_handler(handler):
                continue
            try:
                command = shlex.split(handler["command"])[0]
                resolve_executable("init-agent-hook", command, required=True, verify_explicit=True)
                found = True
            except (ValueError, OSError):
                return False
    return found


def _is_init_agent_handler(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    try:
        parts = shlex.split(str(handler.get("command") or ""))
    except ValueError:
        return False
    return bool(parts) and HOOK_COMMAND_MARKER in parts[1:]


def _read_hooks(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Codex hooks.json is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Codex hooks.json must contain a JSON object")
    return data


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            harden_private_path(temporary)
            handle.write(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _backup_file(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    backup = path.with_name(f"{path.name}.bak-{timestamp}")
    copy_private_file(path, backup)
    return backup


def _codex_hooks_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "hooks.json"
    return DEFAULT_CODEX_HOOKS
