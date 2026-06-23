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
init-agent tool repo_entrypoints --json
init-agent tool repo_related_file --path src/auth/session.py --json
init-agent tool repo_symbol_callers --symbol validateSession --json
init-agent tool repo_feedback_add --query "debug login session redirect" --path src/auth/session.py --rating useful --reason "verified session flow" --json
init-agent tool repo_feedback_explain --query "debug login session redirect" --json
init-agent tool repo_memory_add --path src/auth/session.py --topic "login session" --evidence read_full_file --note "Session validation lives here; verified during redirect debugging." --json
init-agent tool repo_memory_add --scope repo --topic "architecture" --evidence user_decision --note "Use a local-only CLI with SQLite storage." --json
init-agent tool repo_memory_search --query "login session validation" --json
init-agent tool repo_memory_audit --json
init-agent tool repo_memory_topics --topic "login session" --json
init-agent tool repo_memory_list --stale --json
init-agent tool repo_memory_update --id 12 --evidence read_full_file --note "Session validation lives here; refreshed after re-reading the file." --json
```

These commands return stable JSON contracts with candidate files, symbols,
file neighborhoods, callers, commits, follow-up commands, optional local
feedback, local file notes and safety warnings.

Repo-scoped memories can also be recorded before a project has meaningful files
or an index. Use them sparingly for decisions, conventions and created-file
intent that should keep future agent work coherent.

For MCP-capable agents, run the stdio server from the repository root:

```bash
init-agent mcp
```

Or point it at a root explicitly:

```bash
init-agent-mcp --root /path/to/repository
```

The MCP server exposes the same tools: `repo_graph_search`, `repo_overview`,
`repo_entrypoints`, `repo_related_file`, `repo_symbol_callers`,
`repo_feedback_add`, `repo_feedback_explain`, `repo_memory_add`,
`repo_memory_audit`, `repo_memory_list`, `repo_memory_search`,
`repo_memory_topics`, `repo_memory_update`, `repo_memory_delete` and
`repo_file_notes`.

See [mcp.md](mcp.md) for Codex `config.toml` examples and smoke testing.

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
- Keep feedback reasons factual and do not store source snippets.
- Keep memory notes short, factual and tied to files already inspected.
- Treat stale memory notes as hints only; re-read the file before relying on them.
