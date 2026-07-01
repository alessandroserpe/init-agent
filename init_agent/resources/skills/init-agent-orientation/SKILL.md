---
name: init-agent-orientation
description: Use when working inside a code repository and the user asks to inspect, debug, modify, understand, refactor, review, or plan code changes. Runs init-agent to build a local context pack before broad file reads, then uses symbol/caller/related commands for targeted follow-up.
---

# Init Agent Orientation

Use `init-agent` as a local Project Orientation Layer before manually reading many files in a repository.

The goal is to get a compact local context pack that points to likely relevant files, symbols, relations and recent commits. The context pack is a starting point, not a source of truth.

## When To Use

Use this workflow when:

- starting work in an unfamiliar repository
- debugging a feature or bug by free-text query
- planning a change before editing files
- reviewing an area of code without knowing where to start
- the user asks for repo orientation, context, related files, likely entry points, callers, symbols or token savings

Skip it when:

- the task already names exact files and the scope is tiny
- `init-agent` is not installed and installing it would distract from a small task
- the user explicitly says not to run project analysis tools

## Base Workflow

Default to the smallest useful loop:

```bash
init-agent overview
init-agent plan "<user task>" --read 3
# read and verify files directly
init-agent plan finish --id <plan-id> --read-file <path> --verified <path> --useful <path> --summary "short factual outcome"
init-agent session close
```

Use lower-level commands such as `run`, `trace`, `related`, `symbol`,
`callers`, `feedback` and `memory` as targeted follow-ups. Do not turn every
task into every command.

1. From the repository root, check availability:

```bash
init-agent --version
```

2. For broad "orient me in this repository" tasks, build an updated overview:

```bash
init-agent run --overview --markdown
```

3. For specific debugging, review or change tasks, build an updated context pack:

```bash
init-agent run "<user task>" --markdown
```

4. If the repository has local memory/feedback or the task is broad/noisy, build
   a reading plan before opening many files:

```bash
init-agent plan "<user task>" --read 3
```

5. Use the overview, context pack or reading plan to choose the first files to inspect:

- Suggested first reads
- Reading plan actions such as `read`, `verify_stale` or `skip_unless_needed`
- Reading plan read priorities such as `read_now`, `read_if_needed` or `context_only`
- Fresh or stale memory attached to candidate files
- Likely entry points
- Package manifests and config
- Major subsystems
- Related symbols
- Recent related commits
- Reasons for each candidate file

6. Read the suggested files directly from the filesystem before proposing or making code changes.

7. After reading files, keep a tiny verification ledger for yourself:

- verified central files: files that were actually useful for the task
- verified noisy files: files that looked relevant in the ranking but were not
- verified missing files: important files you had to open that were absent from the initial suggestions
- durable facts learned: stable facts about file purpose, project conventions or decisions

Use this ledger before finishing the task to decide whether to record feedback,
memory or a task note. Do not wait for the user to ask.

If you used a saved reading plan, close the loop after verification:

```bash
init-agent plan read --id <plan-id> --file path/to/read-file --note "opened while investigating"
init-agent plan diff --id <plan-id>
init-agent plan finish --id <plan-id> --read-file path/to/read-file --verified path/to/verified-file --useful path/to/useful-file --summary "short factual outcome"
```

For MCP-capable agents, use `repo_reading_plan_read` after opening planned or
unplanned files, `repo_reading_plan_diff` before handoff when the plan is not
obvious, and `repo_reading_plan_finish` after verification. Mark only verified
outcomes. Use `--noisy` for irrelevant candidates and `--missing` for important
files absent from the plan. The read ledger is explicit metadata, not automatic
editor telemetry.

## Targeted Follow-Up

Use more specific commands when the question shape suggests them.

If the user asks where a function/class/symbol is defined or called:

```bash
init-agent symbol "<symbol>"
init-agent callers "<symbol>"
```

If the context pack identifies a likely file and you need its local neighborhood:

```bash
init-agent related path/to/file
```

If the task is about a runtime path, rendering bug, legacy entrypoint flow,
route composition or "where does this page come from?", use trace before broad
reading:

```bash
init-agent trace "<user task>"
```

If the task needs a combined view of graph, trace, memory, feedback, tags and
stale state, use plan:

```bash
init-agent plan "<user task>" --read 3
```

If the task is large or the user asks about context savings:

```bash
init-agent estimate "<user task>"
```

If the project state seems stale or broken:

```bash
init-agent doctor
```

## Noisy Or Empty Results

If the first overview or context pack is empty, stale or noisy, do not give up
and do not start reading the whole repository. Recover in this order:

1. Check readiness:

```bash
init-agent doctor
```

2. If the index is missing, empty or stale, rebuild it:

```bash
init-agent map
```

3. Retry with a narrower query using concrete terms found in the repo or task:

```bash
init-agent run "<specific module, symbol, route, table, error or workflow>" --markdown
```

4. Use targeted follow-ups instead of broad reading:

```bash
init-agent related path/to/candidate-file
init-agent callers SomeSymbol
init-agent symbol SomeSymbol
```

5. After verification, record why the first result was noisy:

```bash
init-agent feedback add "<task>" path/to/noisy-file --rating noisy --source agent --reason "matched query terms but verified unrelated"
init-agent feedback add "<task>" path/to/missing-file --rating missing --source agent --reason "verified important file absent from initial pack"
```

For MCP-capable agents, use the corresponding `repo_*` tools.

Only fall back to broad filesystem exploration after this recovery loop fails.
If you must fall back, inspect a small set of manifests, entry points and search
results, then record feedback/memory so the same failure is less likely next
time.

After verifying files, record useful or noisy feedback locally when it would
help future similar tasks:

```bash
init-agent feedback add "<user task>" path/to/file --rating useful --source agent --reason "verified relevant flow"
init-agent feedback add "<user task>" path/to/noisy-file --rating noisy --source agent --reason "matched words but not useful"
init-agent feedback add "<user task>" path/to/missing-file --rating missing --source agent --reason "verified important file absent from initial pack"
```

When init-agent MCP tools are available, prefer `repo_feedback_add` for the
same workflow after verification.

Feedback is expected after non-trivial verified work when one of these is true:

- the top suggested file was correct and central
- a suggested file was clearly irrelevant/noisy
- an important file was missing from the initial suggestions
- the ranking surprised you and future runs would benefit from the correction

Feedback is still optional for tiny tasks, but do not skip it on multi-file
investigations just because the user did not ask.

When an inspected file contains useful operational knowledge, record a short
local note with `repo_memory_add` or search previous notes with
`repo_memory_search`. Notes should explain what was learned about the file,
not copy source code. Include an evidence level when possible, such as
`read_full_file`, `read_excerpt`, `manifest_only`, `inferred_from_graph`,
`user_decision`, `implementation_note` or `planning_note`.
Use short structured tags when they would help future retrieval, such as
`mcp`, `server_startup`, `login_session` or `crud_builder`.

Memory is expected after non-trivial work when you learned something stable
that would save future context, such as:

- what a large or central file owns
- which file is the real entry point for a workflow
- where a bug class usually belongs
- a project-wide convention or user decision
- why a recurring candidate is a false-positive support file

Use `scope=repo` for project-wide decisions and conventions that are not tied
to one file, especially when a project starts from zero before the first map.
Keep repo memories small; they are for orientation, not project management. If
a memory result is marked stale, re-read the file before relying on the note.
Use `repo_memory_audit` to find stale, vague or duplicate notes,
`repo_memory_topics` for a topic-level area map, `repo_memory_list --stale` to
audit stale notes, `repo_memory_update` to refresh corrected notes after
verification, and `repo_memory_delete` to remove wrong or duplicate notes.

Prefer updating an existing memory over adding a near-duplicate note for the
same file/topic.

For longer work that spans multiple files, modifications, checks or handoff
points, use local task/session memory to keep the operational thread explicit.
Prefer MCP tools when available:

```text
repo_task_add
repo_task_note
repo_task_list
repo_task_update
repo_task_close
```

Use `repo_task_add` when starting a non-trivial task, `repo_task_note` after
meaningful progress or verification, and `repo_task_close` only when the work is
actually done. Link relevant files, tests, memory ids, feedback ids and
remaining follow-up. Do not create local tasks for tiny one-shot questions.

Before finishing a non-trivial task, do a short memory/feedback check:

- If a suggested file was verified and central to the task, record `useful`
  or `crucial` feedback unless the task was tiny.
- If a suggested file matched the query but was irrelevant, record `noisy`
  feedback when the mismatch is clear.
- If an important file was missing from the initial suggestions, record
  `missing` feedback after verifying its relevance.
- If you learned a stable fact about a file or project decision, add or update
  a short memory note with evidence.
- If the work spans multiple steps or needs handoff continuity, consider a
  local task note or close the local task if complete.
- If a reading plan was used, finish it with the files actually read,
  verified, useful, noisy or missing.
- If nothing stable was learned, do not write memory or feedback.

Never write feedback or memory just because a file appeared in a ranking.
Never store source snippets in memory or feedback.

## End Of Session

Before the final response for a non-trivial task, run an end-of-session handoff
check when any of these are true:

- code or documentation was changed
- files were investigated across multiple areas
- memory or feedback was added or updated
- the user asks to wrap up, close, hand off, summarize what remains, take stock or do a final status check
- the session is long enough that stale memory or Git status could matter

Prefer the MCP tool when available:

```text
repo_session_close
```

Otherwise use the CLI:

```bash
init-agent session close
```

Use the result to inform the final answer: mention modified files, stale memory,
open local tasks, unfinished reading plans, memory quality issues, suggested
feedback/memory opportunities, verification still needed and follow-up commands
when they matter. Do not run session close for tiny one-shot answers or when the
user explicitly asks only for a quick fact.

If repeated context packs behave unexpectedly, inspect the local feedback
signals before adding more:

```bash
init-agent feedback explain "<user task>"
init-agent feedback explain "<user task>" --all --json
```

## Query Guidance

- Prefer `init-agent run --overview --markdown` for broad repository orientation.
- Prefer the user's natural-language task first for specific feature, bug, refactor or review questions.
- If the first pack is noisy, retry with concrete terms found in the repository, such as module names, function names, route names, table names or error identifiers.
- For symbol questions, run `symbol` or `callers` instead of repeatedly rephrasing `run`.
- For file questions, run `related` after opening the likely file.
- Record feedback only after reading or otherwise verifying files. Do not mark files useful or noisy from ranking alone.
- Use `feedback explain` when feedback appears to affect a query in a surprising way.

## Output Use

Treat `init-agent run --markdown` as orientation material that can be quoted or summarized for the user. Prefer acting on it by opening the suggested files, not by trusting it blindly.

For machine-readable workflows, use:

```bash
init-agent run "<user task>" --json
```

## Safety Rules

- Do not treat the context pack as source of truth.
- Always verify by reading relevant files before editing.
- Do not commit `.agent/` or generated local index files.
- Do not send repository contents externally.
- Remember that ranking is heuristic; relevant-looking files may be non-essential.
- Keep feedback factual and local; do not store source snippets in feedback reasons.
