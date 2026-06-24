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

4. Use the overview or context pack to choose the first files to inspect:

- Suggested first reads
- Likely entry points
- Package manifests and config
- Major subsystems
- Related symbols
- Recent related commits
- Reasons for each candidate file

5. Read the suggested files directly from the filesystem before proposing or making code changes.

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

If the task is large or the user asks about context savings:

```bash
init-agent estimate "<user task>"
```

If the project state seems stale or broken:

```bash
init-agent doctor
```

After verifying files, record useful or noisy feedback locally when it would
help future similar tasks:

```bash
init-agent feedback add "<user task>" path/to/file --rating useful --source agent --reason "verified relevant flow"
init-agent feedback add "<user task>" path/to/noisy-file --rating noisy --source agent --reason "matched words but not useful"
init-agent feedback add "<user task>" path/to/missing-file --rating missing --source agent --reason "verified important file absent from initial pack"
```

When init-agent MCP tools are available, prefer `repo_feedback_add` for the
same workflow after verification. Feedback is optional; use it only when it
would help future similar tasks.

When an inspected file contains useful operational knowledge, record a short
local note with `repo_memory_add` or search previous notes with
`repo_memory_search`. Notes should explain what was learned about the file,
not copy source code. Include an evidence level when possible, such as
`read_full_file`, `read_excerpt`, `manifest_only`, `inferred_from_graph`,
`user_decision`, `implementation_note` or `planning_note`. Use `scope=repo`
for project-wide decisions and conventions that are not tied to one file,
especially when a project starts from zero before the first map. Keep repo
memories small; they are for orientation, not project management. If a memory
result is marked stale, re-read the file before relying on the note. Use
`repo_memory_audit` to find stale, vague or duplicate notes, `repo_memory_topics`
for a topic-level area map, `repo_memory_list --stale` to audit stale notes,
`repo_memory_update` to refresh corrected notes after verification, and
`repo_memory_delete` to remove wrong or duplicate notes.

Before finishing a non-trivial task, do a short memory/feedback check:

- If a suggested file was verified and central to the task, consider `useful`
  or `crucial` feedback.
- If a suggested file matched the query but was irrelevant, consider `noisy`
  feedback.
- If an important file was missing from the initial suggestions, consider
  `missing` feedback.
- If you learned a stable fact about a file or project decision, consider a
  short memory note with evidence.
- If nothing stable was learned, do not write memory or feedback.

Never write feedback or memory just because a file appeared in a ranking.

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
memory quality issues, verification still needed and follow-up commands when
they matter. Do not run session close for tiny one-shot answers or when the user
explicitly asks only for a quick fact.

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
