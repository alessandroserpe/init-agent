# MCP Integration

`init-agent` includes a minimal MCP stdio server for agents that can consume
Model Context Protocol tools.

The MCP server exposes the same local repo tool contracts as the CLI:

- `repo_graph_search`
- `repo_trace`
- `repo_reading_plan`
- `repo_overview`
- `repo_entrypoints`
- `repo_related_file`
- `repo_symbol_callers`
- `repo_feedback_add`
- `repo_feedback_explain`
- `repo_memory_add`
- `repo_memory_audit`
- `repo_memory_list`
- `repo_memory_search`
- `repo_session_close`
- `repo_session_summary`
- `repo_memory_topics`
- `repo_memory_delete`
- `repo_memory_update`
- `repo_task_add`
- `repo_task_list`
- `repo_task_note`
- `repo_task_update`
- `repo_task_close`
- `repo_file_notes`

It does not call an LLM and does not modify project source files. Most MCP tool
calls are intentionally lazy: they read the existing `.agent/graph.sqlite`
index and return warnings if the index is missing or empty. Feedback tools can
write local feedback metadata to `.agent/graph.sqlite` after an agent verifies
files. Memory tools can store short local notes, also in `.agent/graph.sqlite`.
File-scoped notes report stale status when the indexed file hash changed after
the note was recorded; repo-scoped notes are useful for project-wide decisions
and report stale status as not applicable. Use `repo_memory_audit` to find
stale, vague or duplicate notes. Use `repo_memory_topics` to get a
compact area-level memory map before opening files. Use `repo_memory_update`
after re-reading a stale note to refresh it without creating duplicates. Use
task tools to keep an operational thread for longer work: open task title,
linked files, verification performed and remaining follow-up. Open tasks are
included in `repo_session_summary` and `repo_session_close`. Use
`init-agent run --overview --markdown` or `init-agent run "<task>" --markdown`
first when you want automatic init/map/refresh behavior.

For decision-log and area-map patterns, see
[memory-workflows.md](memory-workflows.md).

## Install

Install with `pipx`:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git --python python3.12
```

If `python3.12` is not on your `PATH`, use the full Python path:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git --python /opt/homebrew/bin/python3.13
```

Verify:

```bash
init-agent --version
init-agent-mcp --help
```

## Smoke Test

This sends two framed JSON-RPC messages to the stdio server. `init-agent-mcp`
supports both common stdio framings:

- `Content-Length` framed JSON-RPC messages.
- JSON-line messages, which Codex may use when launching local MCP servers.

The smoke test below uses `Content-Length` framing:

```bash
python3 - <<'PY'
import json
import subprocess

messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]

payload = b""
for message in messages:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    payload += b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body

result = subprocess.run(["init-agent-mcp", "--root", "."], input=payload, stdout=subprocess.PIPE, check=True)
print(result.stdout.decode("utf-8"))
PY
```

Expected result: framed JSON-RPC responses. The `tools/list` response should
include:

- `repo_graph_search`
- `repo_trace`
- `repo_reading_plan`
- `repo_overview`
- `repo_entrypoints`
- `repo_related_file`
- `repo_symbol_callers`
- `repo_feedback_add`
- `repo_feedback_explain`
- `repo_memory_add`
- `repo_memory_audit`
- `repo_memory_list`
- `repo_memory_search`
- `repo_session_close`
- `repo_session_summary`
- `repo_memory_topics`
- `repo_memory_delete`
- `repo_memory_update`
- `repo_task_add`
- `repo_task_list`
- `repo_task_note`
- `repo_task_update`
- `repo_task_close`
- `repo_file_notes`

## Codex Configuration

Codex supports MCP stdio servers through its own `codex mcp` commands and
through `config.toml`.

Use the installer to call Codex's official MCP registration command:

```bash
init-agent mcp install-codex
```

Under the hood, this runs the equivalent of:

```bash
codex mcp add init_agent -- init-agent-mcp
```

Restart Codex after running it, then check `/mcp` inside Codex. In this
default mode, the server is general: it serves the current Codex session
working directory, the same way other stdio MCP servers are usually registered.

If you intentionally want to pin one server registration to one repository, use
`--root`:

```bash
init-agent mcp install-codex --root /absolute/path/to/repository
```

Codex currently defaults MCP startup to 30 seconds. After registration,
init-agent checks the generated Codex config block and adds:

```toml
startup_timeout_sec = 120
tool_timeout_sec = 120
```

Only the `[mcp_servers.init_agent]` block is touched, and a timestamped backup
is created before changing the file.

If a previous init-agent MCP registration already exists, replace it with:

```bash
init-agent mcp install-codex --replace
```

To remove the registration:

```bash
init-agent mcp uninstall-codex
```

This runs:

```bash
codex mcp remove init_agent
```

### Manual Config Fallback

Directly editing `config.toml` is available only as an explicit experimental
fallback:

```bash
init-agent mcp install-codex --manual-config --experimental
init-agent mcp install-codex --replace --manual-config --experimental
init-agent mcp uninstall-codex --manual-config --experimental
```

The manual fallback preserves the existing Codex config, creates a timestamped
backup when `config.toml` already exists, and edits only the
`[mcp_servers.init_agent]` block.

User-level configuration lives at:

```text
~/.codex/config.toml
```

Project-level configuration can live at:

```text
.codex/config.toml
```

Project-level config is loaded only for trusted projects.

### User-Level Example

This makes one MCP server available from Codex sessions. The server uses the
current working directory used when Codex starts the server:

```toml
[mcp_servers.init_agent]
command = "/Users/me/.local/bin/init-agent-mcp"
args = []
startup_timeout_sec = 120
tool_timeout_sec = 120
```

### Project-Level Example

Inside a repository:

```toml
# .codex/config.toml
[mcp_servers.init_agent]
command = "init-agent-mcp"
args = []
startup_timeout_sec = 120
tool_timeout_sec = 120
```

Then start Codex from that repository root.

### Absolute Root Example

Use an absolute root when a client starts the MCP server from another working
directory:

```toml
[mcp_servers.init_agent]
command = "init-agent-mcp"
args = ["--root", "/Users/me/projects/my-repo"]
startup_timeout_sec = 120
tool_timeout_sec = 120
```

### Limit Exposed Tools

Codex supports tool allow/deny lists for MCP servers. For example, expose only
overview and graph search:

```toml
[mcp_servers.init_agent]
command = "init-agent-mcp"
args = []
enabled_tools = ["repo_overview", "repo_entrypoints", "repo_graph_search"]
```

## Fresh Codex Session Checklist

After installing or upgrading init-agent, use a fresh Codex session to verify
the MCP registration:

```bash
cd /path/to/repository
codex
```

Inside Codex, run:

```text
/mcp
```

Expected result:

- `init_agent` is listed as enabled.
- The repo tools are available, for example `repo_overview`,
  `repo_graph_search`, `repo_reading_plan`, `repo_related_file`,
  `repo_memory_search` and `repo_memory_audit`.
- Calling `repo_overview` reports the same repository root you started Codex
  from, unless you intentionally pinned `--root`.

From the shell, you can inspect the registration with:

```bash
codex mcp get init_agent
codex mcp list
```

Useful caveats:

- Restart Codex after installing, upgrading or replacing an MCP server.
- Prefer the unpinned default registration for normal use. It lets the server
  follow the current Codex session working directory.
- Use `--root /absolute/path` only when you intentionally want a server pinned
  to one repository.
- If tool results mention files from another repository, remove and reinstall
  the server without `--root`, or replace it with the correct root.
- If startup times out, verify `codex mcp get init_agent`, confirm the command
  points to the current `init-agent-mcp`, then reinstall with
  `init-agent mcp install-codex --replace`.

## Notes

- `init-agent-mcp` is a stdio server. It is not meant to be used interactively.
- The server auto-detects input framing and responds with the same framing
  style: `Content-Length` or JSON-line.
- MCP tool calls read the existing local index and do not auto-map or refresh
  the repository.
- MCP clients start the process and exchange JSON-RPC messages through
  stdin/stdout.
- Use `init-agent run --overview --markdown` or `init-agent tool ... --json`
  when you want a human-readable or shell-friendly workflow.
- Treat all results as heuristic orientation. Agents should still read files
  before changing code.
