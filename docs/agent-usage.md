# Agent Usage

`init-agent` is designed to be used by coding agents before they inspect a
repository broadly. It gives the agent a compact map, then the agent verifies
the suggested files directly from the filesystem.

## Recommended Agent Loop

For most non-trivial work, prefer this loop:

```bash
init-agent plan "why does the login session expire after redirect" --read 3
# read and verify the suggested files
init-agent plan finish --id <id> --read-file src/auth/session.py --verified src/auth/session.py --central src/auth/session.py --support tests/test_session.py --summary "Verified session path."
init-agent session close
```

Use `init-agent overview` for broad orientation, `init-agent web` for human
observation, and the lower-level commands below only when they answer a
specific follow-up question.

## Generic Workflow

For broad orientation:

```bash
init-agent overview --markdown
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

For structured agent integrations, prefer the compact MCP `core` profile:

- orient: `repo_overview`, then `repo_reading_plan`;
- investigate: `repo_related_file` or `repo_symbol_callers` only when needed;
- close the loop: `repo_reading_plan_finish`;
- reuse durable context: `repo_memory_search`, `repo_memory_add`;
- hand off: `repo_session_close`.

The CLI and MCP `full` profile retain graph search, trace, scorecard, plan
ledger, feedback maintenance, memory maintenance, task and delegated-workstream
contracts for diagnostics, scripts and compatibility. Do not call them during a
normal task merely because they exist.

These commands return stable JSON contracts with candidate files, symbols, file
neighborhoods, callers, commits, follow-up commands, optional feedback, local
notes and safety warnings.

Use `repo_reading_plan` when local memory exists or when the task is broad
enough that graph ranking alone may be noisy. It combines graph search, trace
paths, file tags, memory notes, feedback and stale state into suggested actions
such as `read`, `verify_stale`, `use_memory_context` and
`skip_unless_needed`. It is still orientation only: stale memory means re-read
the file, not trust the note.

Use `--read N` to keep the first pass bounded. Items marked `read_now` are the
initial file budget; `read_if_needed` and `context_only` are follow-ups. After
verification, call `repo_reading_plan_finish` once with the plan id, the ordered
files read and the actual outcome: verified, central, supporting, created,
verification-only, noisy or missing. This creates a small feedback loop without
requiring separate read/diff calls. The legacy `repo_reading_plan_read` and
`repo_reading_plan_diff` contracts remain in the full profile for scripts that
need incremental bookkeeping. Use
`repo_reading_plan_stats` or `init-agent scorecard` only when local metrics are
useful. They measure orientation quality: whether central files appeared early,
how often important pre-existing files were missing, and how quickly the read
ledger reached a central file. Support, created and verification files are
reported separately. The scorecard also reports observed rank lift from
memory, feedback and tags. It is not proof of agent speed or task success.
Mark smoke, experiment, planning, diagnostic or docs-only plans with
`init-agent plan mark --id <id> --kind <kind>` or
`repo_reading_plan_mark` so the default scorecard focuses on real work.

### Optional Delegation

A reading plan includes delegation advice only when explicitly requested with
`--delegate` or `delegate=true`. Treat it as a coordination
hint, not an instruction to spawn workers. Small or high-confidence plans use
the `direct` strategy. Broader plans may propose one or more bounded,
read-only workstreams and provider-agnostic model tiers (`fast`, `balanced`,
`deep`) with reasoning effort (`low`, `medium`, `high`). The parent agent maps
those hints to capabilities actually available in its environment.

If the parent delegates a proposed workstream, the worker must submit a
structured report with `repo_workstream_report`. The parent then checks the
files, findings and verification evidence and records `accepted`, `rework` or
`rejected` with `repo_workstream_review`. A submitted but unreviewed report, or
a workstream marked `rework`, blocks `repo_reading_plan_finish`. An unused
proposal does not block completion. `init-agent` never launches subagents and
never approves delegated work itself.

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
init-agent tool repo_flow_topics --tag startup --json
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
init-agent-mcp --profile core --root /path/to/repository
```

The MCP server exposes a compact core surface by default. CLI commands and the
MCP `full` profile retain the complete compatibility surface. See
[commands.md](commands.md) for the full command reference.

See [mcp.md](mcp.md) for Codex `config.toml` examples and smoke testing.

## Codex

Install the bundled Codex skill:

```bash
init-agent install-skill codex
```

After `pipx upgrade init-agent`, run:

```bash
init-agent sync
```

This keeps the copied Codex skill aligned with the installed package and
checks MCP registration without rewriting Codex configuration. If a local
skill was edited, init-agent creates a timestamped backup under
`~/.codex/init-agent-backups/skills/` before replacing it. Legacy backups found
inside `~/.codex/skills/` are migrated so Codex cannot load them as duplicate
skills.
`init-agent doctor` compares skill contents offline; remote release checks are
explicit through `init-agent doctor --check-updates`.

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
