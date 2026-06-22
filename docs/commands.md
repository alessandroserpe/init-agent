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
