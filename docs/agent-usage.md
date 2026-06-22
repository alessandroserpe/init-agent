# Agent Usage

`init-agent` is designed to be used by coding agents before they inspect a
repository broadly. It gives the agent a compact map, then the agent verifies
the suggested files directly from the filesystem.

## Generic Workflow

For broad orientation:

```bash
init-agent run --overview --markdown
```

For a specific task:

```bash
init-agent run "why does the login session expire after redirect" --markdown
```

For a function, class or symbol:

```bash
init-agent symbol createSession
init-agent callers createSession
```

For a likely file:

```bash
init-agent related src/auth/session.py
```

For context savings:

```bash
init-agent estimate "debug login session redirect"
```

For structured agent integrations:

```bash
init-agent tool repo_graph_search --query "debug login session redirect" --json
init-agent tool repo_overview --json
init-agent tool repo_related_file --path src/auth/session.py --json
init-agent tool repo_symbol_callers --symbol validateSession --json
```

These commands return stable JSON contracts with candidate files, symbols,
file neighborhoods, callers, commits, follow-up commands and safety warnings.

For MCP-capable agents, run the stdio server from the repository root:

```bash
init-agent mcp
```

Or point it at a root explicitly:

```bash
init-agent-mcp --root /path/to/repository
```

The MCP server exposes the same four tools: `repo_graph_search`,
`repo_overview`, `repo_related_file` and `repo_symbol_callers`.

## Codex

Install the bundled Codex skill:

```bash
init-agent install-skill codex
```

Then open Codex from a repository and ask:

```text
Use the init-agent-orientation skill to orient yourself in this repository.
```

See [../skills/README.md](../skills/README.md) for skill installation,
troubleshooting and local shim setup.

## Other Agents

For Claude Code, Aider, OpenCode and similar tools, use the Markdown workflow
until their native instruction formats are verified:

```bash
init-agent run --overview --markdown
init-agent run "<task>" --markdown
```

Then paste the output into the agent or ask the agent to run those commands.

Dedicated installers for other agents should only be added after testing the
expected files, install paths and reload behavior.

## Safety

- Treat output as orientation, not truth.
- Read the suggested files before changing code.
- Do not commit `.agent/`.
- Record feedback only after verifying files.
