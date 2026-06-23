# Memory Workflows

init-agent memory is a local orientation cache for coding agents. It should help
an agent remember verified facts about a repository without pretending to be the
source of truth.

Use it for short facts that are likely to help future work:

- what a file is responsible for
- which files form an area or runtime flow
- project-wide decisions and conventions
- false positives that should be treated carefully
- notes from a verified implementation or debugging session

Do not use it for full source snippets, long task logs, private credentials or
anything that should live in Git, an issue tracker or documentation.

## Basic Loop

The intended loop is:

1. Search or inspect the graph.
2. Read the real files.
3. Make or review the change.
4. Store only stable facts learned during verification.
5. Audit stale, vague or duplicate notes before trusting them later.

Agents should perform a short end-of-task check before writing anything:

- Was a suggested file verified as central? Consider useful/crucial feedback.
- Was a suggested file irrelevant after inspection? Consider noisy feedback.
- Was an important file missing from the initial suggestions? Consider missing feedback.
- Was a stable fact learned that would save future context? Consider a memory note.
- If the answer is no, write nothing.

Useful commands:

```bash
init-agent tool repo_memory_search --query "server startup" --json
init-agent tool repo_memory_topics --json
init-agent tool repo_memory_audit --json
init-agent tool repo_file_notes --path src/server/app.py --json
```

## Decision Log

Use repo-scoped memories for decisions that affect the whole project or an area
but are not tied to one file.

Good decision notes are short and factual:

```bash
init-agent tool repo_memory_add \
  --scope repo \
  --topic "architecture decisions" \
  --evidence user_decision \
  --note "Keep repository orientation local-only; no LLM calls from init-agent itself." \
  --json
```

Other useful evidence values for decisions are `planning_note` and
`implementation_note`.

Keep decision notes narrow. Prefer one fact per note so an agent can update or
delete it later without losing unrelated context.

## Area Map

Use topics to build a compact area map across files. For example, an agent might
record:

```bash
init-agent tool repo_memory_add \
  --path src/openjarvis/cli/serve.py \
  --topic "server startup" \
  --evidence read_full_file \
  --note "Implements the serve command and starts the API process after config, engine and security setup." \
  --json

init-agent tool repo_memory_add \
  --path src/openjarvis/server/app.py \
  --topic "server startup" \
  --evidence read_excerpt \
  --note "Contains the FastAPI app factory used by the serve command." \
  --json
```

Then later:

```bash
init-agent tool repo_memory_topics --topic "server startup" --notes-per-topic 5 --json
```

This gives the next agent an area-level map before it opens large files.

## Empty Projects

In an empty project, there may be no useful graph yet. Repo-scoped memory can
still preserve decisions while files are being created:

```bash
init-agent tool repo_memory_add \
  --scope repo \
  --topic "project conventions" \
  --evidence user_decision \
  --note "Use standard library Python first; add dependencies only after the interface is stable." \
  --json
```

Once files exist, add file-scoped notes only after reading or writing the real
files.

## Maintenance

Run an audit before relying on old memory or after a long refactoring session:

```bash
init-agent tool repo_memory_audit --json
init-agent tool repo_memory_list --stale --json
```

If a note is stale, re-read the file before using it. Then either update it or
delete it:

```bash
init-agent tool repo_memory_update --id 12 --evidence read_full_file --note "Updated verified fact." --json
init-agent tool repo_memory_delete --id 13 --json
```

Audit output is deliberately conservative. A short note or duplicate topic is
not automatically wrong; it is a signal that the local memory may need cleanup.

## Boundaries

Memory is not a project manager. Task lists, release plans and long histories
belong in normal project artifacts. init-agent memory is for compact repository
orientation that helps an agent decide what to read next.
