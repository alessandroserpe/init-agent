---
name: init-agent-orientation
description: Use when working inside a code repository and the user asks to inspect, debug, modify, understand, refactor, review, or plan code changes. Uses init-agent for a bounded reading plan, targeted graph follow-up, verified feedback, durable local memory, and session handoff.
---

# Init Agent Orientation

Use `init-agent` as a local orientation and memory layer. It suggests where to
start; it does not replace direct file reads, tests, Git inspection or technical
judgment.

## When To Use

Use it when entering an unfamiliar repository, investigating a multi-file task,
debugging from symptoms, reviewing an area, or continuing work that may have
useful local memory.

Skip it when the task already names the exact file and is genuinely tiny, when
the user asks for no repository analysis, or when setup would cost more than the
task.

## Default Loop

Use the smallest useful loop. Do not call every available command.

1. For a new or unfamiliar repository, request `repo_overview`.
2. For a concrete task, request `repo_reading_plan` with `read_budget=3`.
3. Open and verify the suggested files directly.
4. Use `repo_related_file` or `repo_symbol_callers` only when the first reads do
   not resolve the path.
5. Finish once with `repo_reading_plan_finish`, passing the ordered files read
   and verified outcomes.
6. Add memory only for a stable fact that would save a future file read.
7. Use `repo_session_close` before handing off non-trivial work.

The core MCP tools are:

```text
repo_overview
repo_reading_plan
repo_reading_plan_finish
repo_related_file
repo_symbol_callers
repo_memory_search
repo_memory_add
repo_session_close
```

Administrative, diagnostic and legacy tools remain available through the CLI
or the MCP `full` profile. Their existence is not a reason to call them.

## Missing Or Empty Index

MCP reads the existing local index. If overview or plan reports that the index
is missing, empty or stale, prepare it once from the repository root:

```bash
init-agent run --overview --markdown
```

For a specific task you may instead run:

```bash
init-agent run "<user task>" --markdown
```

Do not repeatedly rebuild the map during the same task unless files changed in
a way that materially affects orientation.

Read `preparation.index_health` before trusting overview, plan or targeted
graph results. A `stale` status reports bounded counts and path samples for
changed, removed and unindexed files. The tools may still return useful live
candidates, but deleted paths are filtered and the map should be refreshed
before graph-sensitive work. The freshness probe is read-only, lightweight and
briefly cached; it does not hash or remap the whole repository.

If `init-agent doctor` says the installed skill differs from the bundled copy,
tell the user to run `init-agent sync`. Do not perform remote update checks
implicitly.

## Reading Plan Outcomes

Treat plan results as hypotheses. Read source files before editing or making a
technical claim.

At the end, call `repo_reading_plan_finish` once. Preserve read order and use:

- `central`: the pre-existing file that located or owned the primary behavior
- `support`: a pre-existing file needed after reaching the central area
- `created`: a new implementation file
- `verification`: tests or documentation used to verify the work
- `noisy`: a suggested file verified irrelevant
- `missing`: an important pre-existing file absent from the plan

`repo_reading_plan_finish` records plan events and creates verified orientation
feedback for classified files. Do not add duplicate feedback separately.

Use a non-real `kind` for smoke tests, experiments, diagnostics, planning or
documentation-only runs so scorecard data remains meaningful.

## Targeted Recovery

If the first plan is weak:

1. Narrow the task query using the concrete symptom or symbol.
2. Inspect one likely file with `repo_related_file`.
3. Use `repo_symbol_callers` when a function, class or method name is known.
4. Read a small number of direct search results.
5. Finish the plan with clear `noisy` and `missing` outcomes.

Only then broaden filesystem exploration. Do not keep calling orientation tools
after the relevant implementation path is already known.

`repo_related_file` and `repo_symbol_callers` are compact by default. Use their
counts and truncation flags first; request `include_details=true` only when the
bounded result omits evidence required for the task.

## Memory

Use `repo_memory_search` when returning to a known area or when the plan reports
relevant memory. A fresh note can reduce rereading, but stale notes are only
prompts to verify the live file.

Use `repo_memory_add` only after direct verification. Store short factual notes,
not source snippets, speculation, task narration or temporary implementation
details. Include a topic, concise tags and the strongest truthful evidence:

- `read_full_file`
- `read_excerpt`
- `manifest_only`
- `inferred_from_graph`
- `user_decision`
- `implementation_note`
- `planning_note`

Use file scope for file behavior and repo scope for durable project decisions.
Do not create a near-duplicate note when nothing stable changed.

Memory maintenance such as list, audit, update, delete, topic aggregation and
flow aggregation belongs to CLI/dashboard workflows, not the default coding
loop.

File-scoped freshness checks live file bytes, independently of the map; fresh
means unchanged, not necessarily correct. Editing a note or its tags preserves
the recorded hash and evidence timestamp. After checking the note against the
current file, use `repo_memory_update` with `revalidate=true` (full MCP) or
`init-agent tool repo_memory_update --id <id> --revalidate` (CLI) to renew them.
Do not revalidate merely to clear a stale warning.

## Delegation

Delegation advice is disabled by default. Request it explicitly with
`--delegate` or `delegate=true` only when independent workstreams can genuinely
run in parallel and coordination costs are justified. The parent agent remains
responsible for reviewing worker evidence and the final repository state.

Do not delegate tiny, sequential or tightly coupled tasks.

## End Of Session

Run `repo_session_close` after non-trivial investigation or modification. Use
its checklist to notice a stale repository index, Git changes, stale memory,
unfinished plans, open tasks and missing verification. It is advisory and does
not create commits or modify source files.

Do not run it for a tiny one-shot answer.

## Optional Trajectory

Trajectory hooks, when configured by the user, record redacted lifecycle
metadata automatically. Do not add telemetry calls to the normal repository
workflow and do not install hooks implicitly. If the user explicitly asks for
local trajectory observability, inspect it with `init-agent trajectory status`
and explain that installation requires `init-agent trajectory install-codex`,
review through Codex `/hooks`, and a restart.

The trajectory is not chat history or model reasoning. It must not contain
prompts, full commands, patches, tool output, source snippets or secrets.
An `unknown` tool outcome means evidence is missing, not success or failure.
Use structured outcomes and coverage when interpreting totals; do not infer
success from a zero error count.

## Safety

- Verify live files before editing or relying on memory.
- Keep `.agent/` local and do not commit generated indexes.
- Do not write feedback or memory merely because a file appeared in a ranking.
- Never store source snippets, secrets or personal data in local metadata.
- Tests, lint, type checks and Git status remain authoritative for handoff.
