# MCP Integration

`init-agent` includes a minimal MCP stdio server for agents that can consume
Model Context Protocol tools.

The MCP server exposes the same local repo tool contracts as the CLI:

- `repo_graph_search`
- `repo_overview`
- `repo_related_file`
- `repo_symbol_callers`

It does not call an LLM and does not modify project source files. MCP tool
calls are intentionally lazy: they read the existing `.agent/graph.sqlite`
index and return warnings if the index is missing or empty. Use
`init-agent run --overview --markdown` or `init-agent run "<task>" --markdown`
first when you want automatic init/map/refresh behavior.

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

This sends two framed JSON-RPC messages to the stdio server. MCP stdio uses
`Content-Length` framing:

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
- `repo_overview`
- `repo_related_file`
- `repo_symbol_callers`

## Codex Configuration

Codex supports MCP stdio servers through `config.toml`.

The safest setup path is the assisted installer:

```bash
cd /path/to/repository
init-agent mcp install-codex --root .
```

This command preserves the existing Codex config, creates a timestamped backup
when `config.toml` already exists, and appends only the init-agent MCP server
block. Restart Codex after running it.

If a previous init-agent MCP block already exists, update only that block with:

```bash
init-agent mcp install-codex --root . --replace
```

This also creates a backup first. It is useful when Codex cannot resolve the
`init-agent-mcp` command from its app environment, because the installer prefers
the absolute executable path when it can find one.

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

This makes one MCP server available from Codex sessions. The server root is
the current working directory used when Codex starts the server:

```toml
[mcp_servers.init_agent]
command = "/Users/me/.local/bin/init-agent-mcp"
args = ["--root", "."]
startup_timeout_sec = 120
tool_timeout_sec = 120
```

### Project-Level Example

Inside a repository:

```toml
# .codex/config.toml
[mcp_servers.init_agent]
command = "init-agent-mcp"
args = ["--root", "."]
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
args = ["--root", "."]
enabled_tools = ["repo_overview", "repo_graph_search"]
```

## Notes

- `init-agent-mcp` is a stdio server. It is not meant to be used interactively.
- MCP tool calls read the existing local index and do not auto-map or refresh
  the repository.
- MCP clients start the process and exchange JSON-RPC messages through
  stdin/stdout.
- Use `init-agent run --overview --markdown` or `init-agent tool ... --json`
  when you want a human-readable or shell-friendly workflow.
- Treat all results as heuristic orientation. Agents should still read files
  before changing code.
