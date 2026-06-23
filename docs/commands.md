# Command Reference

Most users can start with `init-agent run`. The lower-level commands are
available when you want more control.

Quoted queries are recommended for shell clarity, but `run`, `context`, `query`
and `estimate` also accept unquoted multi-word text.

## Summary

| Command | Purpose |
|---|---|
| `init-agent init` | Create `.agent/`, `.agent/graph.sqlite` and `.agent/config.json`. |
| `init-agent map` | Build a fresh SQLite index from project metadata. |
| `init-agent refresh` | Incrementally update changed, added and removed files. |
| `init-agent git` | Import Git branch, status and recent commit timeline. |
| `init-agent status` | Print a short project/index summary. |
| `init-agent doctor` | Run read-only diagnostics. |
| `init-agent overview` | Print a broad repository orientation pack. |
| `init-agent run --overview --markdown` | Prepare the project and print an overview. |
| `init-agent run "<task>" --markdown` | Prepare the project and print a context pack. |
| `init-agent tool repo_graph_search --query "<task>" --json` | Return an agent-facing graph search contract. |
| `init-agent tool repo_overview --json` | Return an agent-facing repository overview contract. |
| `init-agent tool repo_entrypoints --json` | Return an agent-facing entry-point discovery contract. |
| `init-agent tool repo_related_file --path <path> --json` | Return an agent-facing file-neighborhood contract. |
| `init-agent tool repo_symbol_callers --symbol <name> --json` | Return an agent-facing symbol caller contract. |
| `init-agent tool repo_feedback_add --query "<task>" --path <path> --rating useful --json` | Record optional local feedback after verification. |
| `init-agent tool repo_memory_add --path <path> --note "..." --json` | Record an optional local note about a verified file. |
| `init-agent tool repo_memory_audit --json` | Audit local memory quality. |
| `init-agent tool repo_session_summary --json` | Summarize local handoff metadata after an agent session. |
| `init-agent tool repo_memory_topics --json` | Summarize local memory by topic/area. |
| `init-agent tool repo_memory_update --id <id> --note "..." --json` | Refresh or replace an existing local note. |
| `init-agent mcp` | Run the MCP stdio wrapper for repo tool contracts. |
| `init-agent estimate "<task>"` | Estimate token savings. |
| `init-agent export --json` | Export the indexed graph metadata for external tools. |
| `init-agent query <text>` | Search paths, symbols, roles and commits. |
| `init-agent context "<task>"` | Build a context pack from the existing index. |
| `init-agent related <path>` | Inspect a file neighborhood. |
| `init-agent callers <symbol>` | Show files that call a symbol/function. |
| `init-agent symbol <symbol>` | Show definitions, callers and candidate files. |
| `init-agent feedback ...` | Manage local orientation feedback. |

## `init-agent init`

Creates:

- `.agent/`
- `.agent/graph.sqlite`
- `.agent/config.json`

It records basic metadata such as project name, root path and whether `.git`
exists. Existing config files are not overwritten.

## `init-agent map`

Scans files and skips heavy or noisy paths such as:

```text
.git, .github, .agent, .agents, .codex, .cursor, .vscode, .idea, .history,
node_modules, vendor, dist, build, .venv, __pycache__, .next,
storage, cache, logs, tmp, temp
```

It also skips OS metadata files, binary/media/archive/font/database extensions,
and Python packaging metadata directories such as `*.egg-info` and
`*.dist-info`.

Extra ignores can be added to `.agent/config.json`:

```json
{
  "exclude_dirs": ["private-cache"],
  "exclude_files": ["local-only.php"],
  "exclude_extensions": [".dump"]
}
```

For each file, it stores path, extension, estimated language, probable role,
size, SHA-256 hash and timestamps. It reads file contents only during mapping
and does not store full source code in the database.

## `init-agent refresh`

Incrementally updates the existing SQLite index:

- indexes new files
- reindexes files whose SHA-256 changed
- skips unchanged files
- removes database records for files that no longer exist

It writes only to `.agent/graph.sqlite` and does not modify project files.

```bash
init-agent refresh
init-agent refresh --json
```

## `init-agent git`

Imports current branch, `git status --short`, latest 50 commits and files
changed by each recent commit. The command is read-only and never commits,
resets, checks out or modifies the repository.

If Git is not present, it prints a clear message and exits successfully.

## `init-agent doctor`

Runs read-only diagnostics for:

- `.agent/`
- `.agent/graph.sqlite`
- `.agent/config.json`
- required SQLite tables
- indexed files, symbols, relations and Git commits
- stale map state
- Git metadata availability
- uncommitted Git changes
- files missing from or stale in the database

Final result is one of:

- `READY`
- `READY_WITH_WARNINGS`
- `NOT_READY`

```bash
init-agent doctor
init-agent doctor --json
```

## `init-agent context <text>`

Builds a compact context pack from indexed SQLite metadata only. It searches
file paths, symbols, roles, languages, Git commit messages, changed files and
simple graph relations.

```bash
init-agent context "fix login session bug"
init-agent context "fix login session bug" --json
```

It returns up to 10 candidate files, 10 related symbols and 5 recent commits.
Large commit file lists are truncated in output.

See [scoring.md](scoring.md) for ranking details.

## `init-agent run <text>`

Runs the automatic mini-harness:

- initializes `.agent/` if needed
- creates config/database if missing
- runs `map` when no files are indexed
- rebuilds the map when the existing index was created with an older extractor
- runs `refresh` when an index already exists
- imports Git metadata when Git is available
- generates a context pack

```bash
init-agent run "login sessione admin"
init-agent run login sessione admin
init-agent run "login sessione admin" --json
init-agent run "login sessione admin" --markdown
```

Use `init-agent run --overview --markdown` for broad repository orientation.

## `init-agent tool repo_graph_search`

Returns a compact JSON contract designed for agent/tool integrations. It uses
the same preparation pipeline as `run`, then reshapes the context pack into
stable tool fields:

```bash
init-agent tool repo_graph_search --query "login session bug" --json
```

The response includes:

- `tool`
- `contract`
- `query`
- `preparation`
- `candidate_files`
- `suggested_first_reads`
- `symbols`
- `related_commits`
- `followup_commands`
- `warnings`

This is not a full MCP server yet. It is the JSON contract that a future MCP
tool can expose without asking an agent to parse terminal Markdown.

## `init-agent tool repo_overview`

Returns the broad repository overview in an agent-facing JSON contract:

```bash
init-agent tool repo_overview --json
```

The response includes preparation state, project metadata, suggested first
reads, likely entry points, package manifests, major subsystems, follow-up
commands and warnings.

## `init-agent tool repo_entrypoints`

Returns a focused contract for likely startup/runtime entry points:

```bash
init-agent tool repo_entrypoints --json
init-agent tool repo_entrypoints --limit 20 --json
```

The response includes likely entry points, supporting files, manifests/config
and follow-up `repo_related_file` commands. It is narrower than
`repo_overview` and useful when an agent asks where a project starts.

## `init-agent tool repo_related_file`

Returns the indexed neighborhood for one file:

```bash
init-agent tool repo_related_file --path src/auth/session.py --json
```

The response includes file metadata, symbols defined in the file, lightweight
relations, resolved calls where available, caller files, recent commits,
co-changed files, follow-up commands and warnings.

## `init-agent tool repo_symbol_callers`

Returns definitions and caller files for a symbol:

```bash
init-agent tool repo_symbol_callers --symbol validateSession --json
```

The response includes definitions, callers, follow-up commands and warnings.
It is designed for agents that need to move from a symbol name to the files
that define or call it.

## `init-agent tool repo_feedback_add`

Records local orientation feedback after a user, agent or benchmark has
verified a file:

```bash
init-agent tool repo_feedback_add --query "fix login session bug" --path src/auth/session.py --rating useful --reason "verified session flow" --json
init-agent tool repo_feedback_add --query "find app entrypoints" --path frontend/src/types/index.ts --rating noisy --reason "type barrel file, not runtime entrypoint" --json
init-agent tool repo_feedback_add --query "find app entrypoints" --path parser.php --rating missing --reason "verified important entrypoint absent from initial pack" --json
```

Ratings are `crucial`, `useful`, `neutral`, `noisy` and `missing`. Feedback is
optional and local. Reasons should be factual and should not contain source
code snippets.

## `init-agent tool repo_feedback_explain`

Explains which local feedback entries would influence a similar query:

```bash
init-agent tool repo_feedback_explain --query "fix login session bug" --json
init-agent tool repo_feedback_explain --query "fix login session bug" --all --json
```

## `init-agent tool repo_memory_add`

Records a short local note about what an agent learned after inspecting a file,
or a repo-wide project note for decisions made before meaningful files exist:

```bash
init-agent tool repo_memory_add --path src/auth/session.py --topic "login session" --query "debug login redirect" --evidence read_full_file --note "Session validation lives here; verified during redirect debugging." --json
init-agent tool repo_memory_add --scope repo --topic architecture --query "start from zero" --evidence user_decision --note "Use a local-only CLI with SQLite storage and no runtime dependencies." --json
```

Memory is optional local working context. Keep notes short, factual and free of
source code snippets. init-agent stores the indexed file hash with each note;
`repo_memory_search` and `repo_file_notes` mark notes stale when the file hash
later changes in the index. Evidence values are `read_full_file`,
`read_excerpt`, `manifest_only`, `inferred_from_graph`, `user_decision`,
`implementation_note` and `planning_note`. File-scoped notes require `--path`;
repo-scoped notes use `--scope repo` and have stale status marked as not
applicable. Repo-scoped notes can be recorded before the first map in an empty
project; use them for compact decisions and conventions, not long project
management logs.

See [memory-workflows.md](memory-workflows.md) for decision-log and area-map
patterns using repo-scoped memories and topics.

## `init-agent tool repo_memory_list`

Lists local file notes, optionally filtered by file, topic or stale status:

```bash
init-agent tool repo_memory_list --json
init-agent tool repo_memory_list --path src/auth/session.py --json
init-agent tool repo_memory_list --topic "login session" --json
init-agent tool repo_memory_list --scope repo --json
init-agent tool repo_memory_list --stale --json
```

## `init-agent tool repo_memory_search`

Searches local file notes:

```bash
init-agent tool repo_memory_search --query "login session validation" --json
init-agent tool repo_memory_search --query "badge unread count" --path src/ui/messages.js --json
```

## `init-agent tool repo_memory_topics`

Returns compact topic-level aggregates from local memory notes:

```bash
init-agent tool repo_memory_topics --json
init-agent tool repo_memory_topics --topic "server startup" --notes-per-topic 3 --json
```

This is useful when an agent wants an area map before opening files. It groups
notes by topic, reports note/file/stale counts and includes recent notes for
each topic.

For a practical workflow, see [memory-workflows.md](memory-workflows.md).

## `init-agent tool repo_memory_audit`

Reports memory quality signals so agents can keep local notes useful:

```bash
init-agent tool repo_memory_audit --json
init-agent tool repo_memory_audit --limit 200 --json
```

The audit reports stale notes, notes with unknown evidence, missing topics,
likely duplicate file/topic groups and overly short notes. Use it before adding
many new memories or after a long refactoring session.

## `init-agent tool repo_session_summary`

Returns a compact local handoff summary for agents:

```bash
init-agent tool repo_session_summary --json
init-agent tool repo_session_summary --limit 20 --json
```

The summary includes project/root metadata, Git status, recent memory notes,
recent feedback and memory audit counts. It does not record a session, modify
source files or replace tests/direct file reads.

## `init-agent tool repo_file_notes`

Lists local notes attached to one file:

```bash
init-agent tool repo_file_notes --path src/auth/session.py --json
```

## `init-agent tool repo_memory_delete`

Deletes one local file note by id:

```bash
init-agent tool repo_memory_delete --id 12 --json
```

## `init-agent tool repo_memory_update`

Updates one local memory note by id and refreshes its stored file hash when
the note is file-scoped:

```bash
init-agent tool repo_memory_update --id 12 --evidence read_full_file --note "Session validation lives here; refreshed after re-reading the file." --json
init-agent tool repo_memory_update --id 13 --topic "runtime entrypoints" --json
```

The command does not change the memory scope or path. Use it after re-reading a
file, correcting a stale note or tightening a repo-wide project decision.

## `init-agent mcp`

Runs a minimal MCP stdio server exposing the same repo tool contracts:

```bash
init-agent mcp
init-agent mcp --root /path/to/repository
init-agent-mcp --root /path/to/repository
init-agent mcp install-codex
init-agent mcp install-codex --root /path/to/repository
init-agent mcp uninstall-codex
```

The server exposes:

- `repo_graph_search`
- `repo_overview`
- `repo_entrypoints`
- `repo_related_file`
- `repo_symbol_callers`
- `repo_feedback_add`
- `repo_feedback_explain`
- `repo_memory_add`
- `repo_memory_audit`
- `repo_memory_list`
- `repo_memory_search`
- `repo_session_summary`
- `repo_memory_topics`
- `repo_memory_delete`
- `repo_memory_update`
- `repo_file_notes`

The server does not modify project source files and is lazy against the
existing SQLite index. Feedback and memory tools may write metadata to
`.agent/graph.sqlite`. MCP tool calls do not auto-map or refresh the
repository; use `init-agent run --overview --markdown` or
`init-agent run "<task>" --markdown` first when you want automatic preparation.
It does not call an LLM and does not send source code over the network.

See [mcp.md](mcp.md) for Codex MCP setup, the `codex mcp add` flow and smoke
testing.

## `init-agent overview`

Builds a broad repository orientation pack from the existing SQLite index. It
does not read full file contents and does not call an LLM.

Overview mode prefers package manifests, README/config files, likely CLI/server
entry points, router files, route symbols, project scripts and major top-level
subsystems.

```bash
init-agent overview
init-agent overview --json
init-agent overview --markdown
init-agent run --overview --markdown
```

## `init-agent estimate <text>`

Prepares the project like `run`, builds the context pack, and estimates token
savings with `ceil(characters / 4)`.

```bash
init-agent estimate "login sessione admin"
init-agent estimate "login sessione admin" --json
```

## `init-agent export`

Exports the local graph as JSON for external tools, visualizers or future agent
tool integrations.

```bash
init-agent export --json
```

The export includes project metadata, stats, files, symbols, relations, recent
Git commits, local feedback and runs. It does not include full source file
contents.

## Symbol And File Commands

```bash
init-agent related path/to/file.py
init-agent callers buildForm
init-agent symbol buildForm
```

`related` shows symbols, relations, PHP calls, caller files and recent commits
around one file.

`callers` shows indexed definitions and files that call a symbol.

`symbol` combines definitions, callers, candidate files and recent commits.
