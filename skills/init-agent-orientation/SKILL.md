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

2. Build an updated context pack for the user's task:

```bash
init-agent run "<user task>" --markdown
```

3. Use the context pack to choose the first files to inspect:

- Suggested first reads
- Related symbols
- Recent related commits
- Reasons for each candidate file

4. Read the suggested files directly from the filesystem before proposing or making code changes.

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

## Query Guidance

- Prefer the user's natural-language task first.
- If the first pack is noisy, retry with concrete terms found in the repository, such as module names, function names, route names, table names or error identifiers.
- For symbol questions, run `symbol` or `callers` instead of repeatedly rephrasing `run`.
- For file questions, run `related` after opening the likely file.

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
