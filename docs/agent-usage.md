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
init-agent tool repo_reading_plan --query "debug login session redirect" --json
init-agent tool repo_overview --json
init-agent tool repo_entrypoints --json
init-agent tool repo_related_file --path src/auth/session.py --json
init-agent tool repo_symbol_callers --symbol validateSession --json
init-agent tool repo_feedback_add --query "debug login session redirect" --path src/auth/session.py --rating useful --reason "verified session flow" --json
init-agent tool repo_feedback_explain --query "debug login session redirect" --json
init-agent tool repo_memory_add --path src/auth/session.py --topic "login session" --tag login_session --evidence read_full_file --note "Session validation lives here; verified during redirect debugging." --json
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

Use `repo_reading_plan` when local memory exists or when the task is broad
enough that graph ranking alone may be noisy. It combines graph search, trace
paths, file tags, memory notes, feedback and stale state into suggested actions
such as `read`, `verify_stale`, `use_memory_context` and
`skip_unless_needed`. It is still orientation only: stale memory means re-read
the file, not trust the note.

Context packs also include a confidence diagnostic and suggested next agent
actions. If confidence is low or medium, agents should follow those actions
before broad filesystem exploration: check `doctor`, rebuild stale indexes with
`map`, retry with a narrower query, inspect related files/symbols and record
noisy or missing feedback after verification.

Use `trace` when the task is about a runtime path rather than a single symbol
match: frontend/rendering bugs, legacy PHP pages, route-to-view flows, CLI
startup or “where does this page come from?” questions.

```bash
init-agent trace "bug frontend h1 title"
init-agent tool repo_trace --query "bug frontend h1 title" --json
```

`trace` returns investigation paths such as
`index.php -> include/page.php`. It is a follow-up orientation view: verify the
suggested files directly before changing code.

For failing-test or symptom-heavy debugging, the first context pack can point at
high-level files that describe the symptom rather than the lower-level cause.
When `next_agent_actions` suggests `related <test-file>`, agents should do that
early: the failing test neighborhood can expose implementation files through
imports, calls and recent co-change history before the agent scans broadly.

For feedback specifically, use the loop documented in
[feedback.md](feedback.md): run orientation, verify files, record useful/noisy/
missing feedback only for verified outcomes, then inspect
`repo_feedback_explain` before trusting future ranking changes.

Repo-scoped memories can also be recorded before a project has meaningful files
or an index. Use them sparingly for decisions, conventions and created-file
intent that should keep future agent work coherent.

For longer-running work, use topics as a lightweight area map and repo-scoped
notes as a compact decision log. Keep both short and factual:

```bash
init-agent tool repo_memory_add --scope repo --topic "architecture decisions" --evidence user_decision --note "Keep the indexing layer local-only and dependency-light." --json
init-agent tool repo_memory_topics --topic "architecture decisions" --json
```

See [memory-workflows.md](memory-workflows.md) for practical decision-log,
area-map and audit patterns.

At the end of a non-trivial task, agents should briefly ask whether local
feedback or memory would help future work. Record nothing by default. Record
only verified, stable facts:

- mark verified central files as `useful` or `crucial`;
- mark irrelevant suggestions as `noisy`;
- mark verified important omissions as `missing`;
- add short memory notes only for facts worth reusing.

For MCP-capable agents, run the stdio server from the repository root:

```bash
init-agent mcp
```

Or point it at a root explicitly:

```bash
init-agent-mcp --root /path/to/repository
```

The MCP server exposes the same tools: `repo_graph_search`, `repo_trace`,
`repo_reading_plan`, `repo_overview`, `repo_entrypoints`,
`repo_related_file`, `repo_symbol_callers`, `repo_feedback_add`,
`repo_feedback_explain`, `repo_memory_add`,
`repo_memory_audit`, `repo_memory_list`, `repo_memory_search`,
`repo_session_summary`, `repo_session_close`, `repo_memory_topics`,
`repo_memory_update`, `repo_memory_delete` and `repo_file_notes`.

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
