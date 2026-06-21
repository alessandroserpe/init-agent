# init-agent

**Give your coding agent a map before it touches your code.**

`init-agent` is a local CLI that builds a compact project map for AI coding agents.
It scans your repository, indexes files, symbols, lightweight relations and Git history,
then produces small context packs so an agent knows where to start without reading the whole repo.

The core idea is simple: do not send the whole repo to the model; build a local map.

There is no built-in LLM execution. `init-agent` prepares local context packs that can be pasted into or consumed by coding agents.

## Quick Start

Run it from the root of the project you want to orient:

```bash
cd your-project
init-agent run "fix login session bug" --markdown
```

This automatically initializes `.agent/`, maps or refreshes the index, imports Git metadata when available, and prints a compact context pack.

For a token estimate:

```bash
init-agent estimate "fix login session bug"
```

For a broad repository orientation:

```bash
init-agent run --overview --markdown
```

## Why It Matters

On a private PHP codebase with 274 indexed readable files:

- Full indexed project estimate: ~350,876 tokens
- Context pack for `login sessione admin`: ~839 tokens
- Estimated context pack + suggested first reads: ~3,050 tokens
- Estimated initial context reduction: ~99.1%

Token estimates use a simple `ceil(characters / 4)` heuristic.

## What It Does

- Initializes a local `.agent/` workspace
- Stores an interrogable SQLite index
- Scans project files while skipping heavy directories, generated files and binaries
- Detects likely language and file role
- Extracts basic symbols from Python, PHP, JavaScript, TypeScript, Go and Rust
- Extracts lightweight documentation/config signals such as Markdown headings, README command examples, config keys and package entry points
- Extracts lightweight route signals for common PHP, Express/Fastify, Flask/Django and Gin patterns
- Records simple relations such as imports/includes, PHP function calls, file language and file role
- Reads Git branch, status and recent commit timeline without modifying the repository
- Produces terminal, JSON and Markdown context packs
- Estimates token savings
- Uses Python 3.11+ and the standard library only

## What init-agent Is Not

- Not a coding agent
- Not an LLM wrapper
- Not a replacement for Codex, Claude Code, Aider, OpenCode or Pi
- Not a semantic code analyzer
- Not a documentation ingester that stores full prose
- Not a tool that modifies your source code

It is a local orientation layer that helps those tools start from better context.

## Installation

From a local checkout:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Manual Commands

Most users can start with `init-agent run`. The lower-level commands are available when you want more control:

```bash
init-agent init
init-agent map
init-agent refresh
init-agent refresh --json
init-agent git
init-agent status
init-agent doctor
init-agent doctor --json
init-agent overview
init-agent overview --json
init-agent run "fix login session bug"
init-agent run --overview --markdown
init-agent run "fix login session bug" --json
init-agent run "fix login session bug" --markdown
init-agent estimate "fix login session bug"
init-agent estimate "fix login session bug" --json
init-agent query auth
init-agent context "fix login session bug"
init-agent context "fix login session bug" --json
init-agent related path/to/file.py
init-agent callers buildForm
init-agent symbol buildForm
init-agent feedback add "fix login session bug" src/auth/session.py --rating useful --source agent
init-agent feedback list
init-agent feedback explain "fix login session bug"
init-agent feedback export --json
```

Quoted queries are recommended for shell clarity, but `run`, `context`, `query`
and `estimate` also accept unquoted multi-word text.

## Use With Coding Agents

`init-agent` is most useful when an agent runs it before broad repository
inspection:

```bash
init-agent run "why does the message badge not update after reply?" --markdown
```

Then the agent should read the suggested files and verify the answer directly
from source code.

For function or class questions, use the targeted commands:

```bash
init-agent symbol buildForm
init-agent callers buildForm
init-agent related include/buildForm.php
```

After verifying files, an agent can record local feedback:

```bash
init-agent feedback add "why does the message badge not update after reply?" \
  js/app.footer.js \
  --rating crucial \
  --source agent \
  --reason "verified client-side badge update flow"
```

Future similar context packs can use that local feedback as a small, bounded
ranking signal.

To inspect why feedback is or is not affecting a repeated query:

```bash
init-agent feedback explain "why does the message badge not update after reply?"
init-agent feedback explain "why does the message badge not update after reply?" --json
```

This repository includes an optional Codex skill template:

```bash
mkdir -p ~/.codex/skills
cp -R skills/init-agent-orientation ~/.codex/skills/
```

The skill tells Codex to use `run`, `symbol`, `callers`, `related`, `estimate`
and `doctor` as an orientation workflow. See [skills/README.md](skills/README.md)
for shim setup, troubleshooting and copy-paste instructions for other CLI
agents.

### `init-agent init`

Creates:

- `.agent/`
- `.agent/graph.sqlite`
- `.agent/config.json`

It records basic metadata such as project name, root path and whether `.git` exists.

### `init-agent map`

Scans files and skips:

```text
.git, .github, .agent, .agents, .codex, .cursor, .vscode, .idea, .history,
node_modules, vendor, dist, build, .venv, __pycache__, .next,
storage, cache, logs, tmp, temp
```

It also skips common OS metadata files such as `.DS_Store`, `Thumbs.db` and `desktop.ini`, plus binary or graph-noisy extensions such as images, archives, fonts, media files, PDFs and local database files.

Python packaging metadata directories such as `*.egg-info` and `*.dist-info` are also skipped.

Extra ignores can be added to `.agent/config.json`:

```json
{
  "exclude_dirs": ["private-cache"],
  "exclude_files": ["local-only.php"],
  "exclude_extensions": [".dump"]
}
```

These values are added to the defaults. Existing config files are not overwritten by `init-agent init`.

For each file, it stores:

- relative path
- extension
- estimated language
- probable role
- size
- SHA-256 hash
- last modified timestamp
- indexed timestamp

It reads file contents only during mapping and does not store full source code in the database.

For PHP projects, `map` also records conservative global function call relations such as `index.php calls buildForm`, while skipping common language constructs and method/static calls.

### `init-agent refresh`

Incrementally updates the existing SQLite index.

It scans the filesystem with the same exclusions used by `map`, compares real files with records already stored in `.agent/graph.sqlite`, and then:

- indexes new files
- reindexes files whose SHA-256 changed
- skips unchanged files
- removes database records for files that no longer exist

It writes only to `.agent/graph.sqlite`. It does not modify project files.

Example:

```bash
init-agent refresh
```

Terminal output includes:

- scanned file count
- unchanged count
- added files
- updated files
- removed files
- final result

JSON output:

```bash
init-agent refresh --json
```

Shape:

```json
{
  "status": "OK",
  "scanned_files": 120,
  "unchanged": 110,
  "added": ["src/new_file.py"],
  "updated": ["src/auth/login.py"],
  "removed": ["old/legacy.php"],
  "errors": []
}
```

If the project has not been initialized, run `init-agent init`. If the database exists but has no indexed files, run `init-agent map` first.

### `init-agent git`

If Git is available, it imports:

- current branch
- `git status --short`
- latest 50 commits
- files changed by each recent commit

This command is read-only. It does not commit, reset, checkout or modify the repository.

If Git is not present, it prints a clear message and exits successfully.

### `init-agent status`

Shows a clean summary:

- project
- root
- Git availability
- current branch
- indexed file count
- symbol count
- relation count
- last map update
- modified files according to Git

### `init-agent doctor`

Runs read-only diagnostics to check whether the project is ready to use `init-agent` as a Project Orientation Layer.

It checks:

- `.agent/`
- `.agent/graph.sqlite`
- `.agent/config.json`
- required SQLite tables
- indexed file, symbol, relation and Git commit counts
- whether Git exists
- whether Git metadata was indexed
- uncommitted Git changes
- files changed after the last map
- indexed files that no longer exist
- real project files missing from the database, respecting scanner exclusions

Example:

```bash
init-agent doctor
```

Terminal output is grouped into:

- `Status`
- `Index`
- `Warnings`
- `Final result`
- `Suggested commands`

Final result is one of:

- `READY`
- `READY_WITH_WARNINGS`
- `NOT_READY`

JSON output:

```bash
init-agent doctor --json
```

Shape:

```json
{
  "status": "READY_WITH_WARNINGS",
  "checks": [
    {
      "name": "database",
      "ok": true,
      "severity": "info",
      "message": "Database is present."
    }
  ],
  "stats": {
    "files": 120,
    "symbols": 430,
    "relations": 900,
    "git_commits": 50,
    "last_map": "2026-06-19T18:30:00+00:00"
  },
  "warnings": [],
  "suggested_commands": []
}
```

`doctor` does not create folders, create databases, run map, import Git history or modify the repository.

### `init-agent query <text>`

Runs a simple non-AI search across:

- file paths
- symbol names
- commit messages
- file roles

It returns up to 20 terminal-friendly results ordered by simple relevance.

### `init-agent context <text>`

Builds a compact context pack for a future AI agent without calling an LLM.

It searches only the indexed SQLite metadata:

- file paths
- symbol names
- file roles and languages
- Git commit messages and changed files, when imported
- simple graph relations

Example:

```bash
init-agent context "fix login session bug"
```

Terminal output includes:

- suggested first files to read
- normalized relevance score
- readable reasons
- related symbols
- recent related commits

JSON output:

```bash
init-agent context "fix login session bug" --json
```

Shape:

```json
{
  "query": "fix login session bug",
  "candidate_files": [
    {
      "path": "src/auth/login.py",
      "score": 1.0,
      "language": "python",
      "role": "source",
      "reasons": ["path matches \"login\"", "symbol matches \"login\""]
    }
  ],
  "suggested_first_reads": ["src/auth/login.py"],
  "related_symbols": [
    {
      "name": "loginUser",
      "kind": "function",
      "file": "src/auth/login.py",
      "line": 3
    }
  ],
  "recent_commits": [
    {
      "hash": "abc123",
      "date": "2026-01-01T00:00:00+00:00",
      "message": "fix login session bug",
      "files": ["src/auth/login.py"]
    }
  ]
}
```

Scoring is intentionally simple, metadata-only and repository-adaptive:

- query tokens are weighted by local rarity across indexed paths, filenames, symbol names, roles, languages and commit messages
- `map`, changed-file `refresh` and Git import rebuild local `term_stats` so common vocabulary in one repository does not dominate every query
- generic request words such as `file`, `repo`, `repository` and `project` are ignored as query noise
- small language function words such as `why`, `where`, `and`, `are`, `not`, `after`, `perché`, `dove` and similar terms are filtered before scoring
- direct path matches are strong signals
- filename matches are stronger than generic path matches
- path and filename matches are boundary-aware, so tiny incidental substrings do not dominate natural-language queries
- conservative soft path/filename matches help with close lexical variants without hardcoded domain synonyms
- symbol matches are useful, but repeated matches for the same token in one file do not stack endlessly
- commit message matches are secondary signals
- relation boosts are capped so linked files cannot beat direct path matches only through many relations
- role and language matches contribute a small relevance boost
- test files are reduced for non-test-aware queries, so operational searches prefer source files; query words such as `test`, `pytest`, `coverage`, `spec` or `fixture` keep test files fully ranked
- asset/style files are reduced for non-UI queries, migration/SQL files for non-database queries, documentation for non-docs queries, and examples/playgrounds for non-example queries
- source files with backend/code extensions get a small preference

The command returns at most 10 candidate files, 10 related symbols and 5 recent commits.
Each recent commit includes at most 10 changed files in output; large commits report `total_files` and `files_truncated`.

### `init-agent run <text>`

Runs the automatic mini-harness:

- initializes `.agent/` if needed
- creates config/database if missing
- runs `map` when no files are indexed
- rebuilds the map when the existing index was created with an older extractor
- runs `refresh` when an index already exists
- imports Git metadata when Git is available
- generates a context pack

Examples:

```bash
init-agent run "login sessione admin"
init-agent run login sessione admin
init-agent run "login sessione admin" --json
init-agent run "login sessione admin" --markdown
```

Use `init-agent run --overview --markdown` when an agent needs a broad first
map of a repository before a specific task. `--json` returns preparation
metadata plus the context pack or overview pack. `--markdown` returns a compact
artifact designed to paste into an AI agent.

### `init-agent overview`

Builds a broad repository orientation pack from the existing SQLite index. It
does not read full file contents and does not call an LLM.

Overview mode prefers general repository signals:

- package manifests such as `pyproject.toml`, `package.json`, `composer.json`, `go.mod` and `Cargo.toml`
- README and configuration files
- likely CLI, server, app, router and entry-point files
- Python framework package initializers such as `management/__init__.py`, `commands/__init__.py`, `cli/__init__.py`, `server/__init__.py` and `api/__init__.py`
- route symbols and project/package scripts extracted during `map`
- major top-level subsystems by indexed files, languages and roles

Examples:

```bash
init-agent overview
init-agent overview --json
init-agent overview --markdown
init-agent run --overview --markdown
```

Overview is heuristic. It is meant to tell an agent where to start, not to
replace direct file reads.

### `init-agent estimate <text>`

Prepares the project like `run`, builds the context pack, and estimates token savings with a simple `ceil(characters / 4)` formula.

It reports:

- context pack characters and estimated tokens
- token cost of suggested first reads if fully read
- token cost of top 10 candidate files if fully read
- token cost of all indexed readable files if fully read
- estimated savings percentages

Examples:

```bash
init-agent estimate "login sessione admin"
init-agent estimate "login sessione admin" --json
```

This command does not call an LLM or send data anywhere.

### `init-agent feedback`

Stores local orientation feedback after a user, agent or benchmark verifies
whether a suggested file was useful. It does not call an LLM and does not store
source code.

Ratings:

- `crucial`: verified as one of the first files an agent should read
- `useful`: relevant supporting file
- `neutral`: recorded context without ranking effect
- `noisy`: matched but was not useful for the task
- `missing`: useful file that was absent from the context pack

Examples:

```bash
init-agent feedback add "fix login session bug" src/auth/session.py --rating crucial --source agent
init-agent feedback add "fix login session bug" README.md --rating noisy --reason "matched words but not useful"
init-agent feedback list
init-agent feedback list --json
init-agent feedback explain "fix login session bug"
init-agent feedback explain "fix login session bug" --all --json
init-agent feedback export --json
init-agent feedback import feedback.json --json
init-agent feedback clear --path README.md
init-agent feedback clear --all
```

Feedback affects `context` and `run` only when query tokens are similar enough.
The score contribution is capped, so old feedback cannot override strong direct
path, filename, symbol or call matches. Context reasons stay explicit:

```text
previously marked crucial for similar query
previously marked noisy for similar query
```

Use `feedback explain` when a repeated query improves or gets worse and you
want to see which local feedback entries matched, their token similarity and
their bounded score contribution. With `--all`, it also shows feedback that was
ignored because it was below the similarity threshold or pointed to a file that
is no longer indexed.

### `init-agent related <path>`

Shows:

- symbols defined in the file
- file relations
- PHP function calls from this file, resolved to definitions when indexed
- other files that call symbols defined in this file
- recent commits that changed the file
- other files changed in the same commits

### `init-agent callers <symbol>`

Shows indexed definitions for a function or symbol name and files that call it.

For PHP procedural projects, this is useful when starting from a global helper
such as `buildForm` and asking where it is used.

### `init-agent symbol <symbol>`

Shows a compact symbol orientation view:

- indexed definitions
- caller files with call counts and first call line
- candidate files from the context scorer
- recent commits related to those candidates

This is useful when you know a function name and want both directions: where it
is defined and where to start reading around it.

## Examples

```bash
init-agent init
init-agent map
init-agent refresh
init-agent refresh --json
init-agent doctor
init-agent doctor --json
init-agent run "add graph export"
init-agent run "add graph export" --markdown
init-agent estimate "add graph export"
init-agent query controller
init-agent query migration
init-agent context "add graph export"
init-agent context "add graph export" --json
init-agent related init_agent/scanner.py
init-agent callers buildForm
init-agent symbol buildForm
```

## Validation Experiments

This repository includes a small local evaluation harness in `experiments/`.
It compares context-pack candidates against expected useful files for real
repositories such as Django, Express, Flask, Fastify, Gin, mini-redis,
Requests, Vite, pytest and Vue Core. The manifest also includes counter-cases
where docs, examples, CSS or tests are intentionally relevant, so scoring
changes are checked against both noise reduction and recall.

```bash
python3 experiments/evaluate.py
python3 experiments/evaluate.py --case django-auth-session-middleware
python3 experiments/evaluate.py --strict
python3 experiments/evaluate.py --strict --rebuild-index
python3 experiments/evaluate.py --case django-auth-session-middleware --measure-manual-scan
```

The script reports top-1/top-3/top-5 hits, obvious noise matches and elapsed
time. It also reports how many indexed files a broad scan would touch compared
with the compact candidate set. Missing benchmark repositories under `/tmp` are
skipped. Use `--case <name>` to isolate one query and `--rebuild-index` after
changing scanner, symbol extraction, role detection or scoring code.

SQLite can also be inspected directly:

```bash
sqlite3 .agent/graph.sqlite ".tables"
sqlite3 .agent/graph.sqlite "select path, language, role from files limit 10;"
```

## Database

The SQLite database includes:

- `project_meta`
- `files`
- `symbols`
- `relations`
- `git_commits`
- `git_commit_files`
- `runs`
- `term_stats`
- `orientation_feedback`

The database stores metadata, symbols and relationships. It intentionally does not store full file contents.

## Philosophy

Large repositories should not be blindly pasted into model context. A future AI agent should first know where it is, what files exist, what symbols are defined, how modules appear to relate, and what recently changed.

`init-agent` builds that local orientation layer. The model can later query the map instead of reading everything at once.

## Security And Privacy

All data is stored locally under `.agent/`. The CLI does not contact external services and does not send repository contents anywhere.

File contents may be read locally during mapping, refresh and token estimation to extract lightweight metadata, symbols, hashes and character counts. Full source code is not persisted in SQLite.

Review `.agent/` before publishing a repository if you choose to commit generated metadata. In most projects, `.agent/` should stay ignored.

## Current Limits

- Symbol extraction is regex-based and intentionally shallow.
- Import/include resolution is best-effort.
- No semantic code understanding.
- No built-in LLM execution.
- No graph visualization yet.
- Context packs use indexed metadata only, so they improve after running `map` and `git`.
- Ranking is heuristic and may surface relevant-looking but non-essential files.
- Context packs are a starting point, not a source of truth. Agents should still verify by reading files.
- Refresh is incremental by file hash, but it does not yet do dependency-aware cascading updates.
- Feedback ranking is local and heuristic; agents should still verify files before relying on prior feedback.

## Roadmap

- Stronger repository overview mode for broad "orient me in this repo" tasks.
- Optional tree-sitter support for more precise parsing.
- JSON graph export for external tools and visualization.
- Direct agent integrations via MCP, plugins or tool APIs.
- Tool `repo_graph_search` for agent runtimes.
- Link chat and agent sessions to repository context packs.
- Dependency-aware incremental updates.
- Graph visualization.
- Language and framework plugin support.

## Development

Run tests:

```bash
python -m unittest discover -s tests -v
```

Run the CLI without installing:

```bash
python -m init_agent.cli --help
```
