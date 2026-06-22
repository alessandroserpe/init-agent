"""Install MCP client configuration snippets."""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
DEFAULT_SERVER_NAME = "init_agent"
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def install_codex_mcp_config(
    root: Path,
    config_path: Path | None = None,
    server_name: str = DEFAULT_SERVER_NAME,
    command: str = "init-agent-mcp",
) -> dict[str, Any]:
    if not SERVER_NAME_RE.match(server_name):
        raise ValueError("server name must contain only letters, numbers, underscores or hyphens")

    target_config = config_path or DEFAULT_CODEX_CONFIG
    target_config = target_config.expanduser()
    resolved_root = root.expanduser().resolve()
    section_header = f"[mcp_servers.{server_name}]"
    block = _config_block(section_header, command, resolved_root)

    original = ""
    if target_config.exists():
        original = target_config.read_text(encoding="utf-8")
        if section_header in original:
            return {
                "installed": False,
                "status": "exists",
                "config_path": str(target_config),
                "backup_path": None,
                "server_name": server_name,
                "root": str(resolved_root),
                "message": f"Codex MCP server already exists: {section_header}",
            }

    target_config.parent.mkdir(parents=True, exist_ok=True)
    backup_path = _backup_config(target_config) if target_config.exists() else None
    with target_config.open("a", encoding="utf-8") as fh:
        if original and not original.endswith("\n"):
            fh.write("\n")
        if original and not original.endswith("\n\n"):
            fh.write("\n")
        fh.write(block)

    return {
        "installed": True,
        "status": "installed",
        "config_path": str(target_config),
        "backup_path": str(backup_path) if backup_path else None,
        "server_name": server_name,
        "root": str(resolved_root),
        "message": "Codex MCP config updated. Restart Codex to load init-agent MCP tools.",
    }


def _backup_config(config_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
    counter = 1
    while backup_path.exists():
        backup_path = config_path.with_name(f"{config_path.name}.bak-{timestamp}-{counter}")
        counter += 1
    shutil.copy2(config_path, backup_path)
    return backup_path


def _config_block(section_header: str, command: str, root: Path) -> str:
    return (
        f"{section_header}\n"
        f'command = "{_toml_string(command)}"\n'
        f'args = ["--root", "{_toml_string(str(root))}"]\n'
        "startup_timeout_sec = 30\n"
        "tool_timeout_sec = 120\n"
    )


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
