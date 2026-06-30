# init-agent

[![CI](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml)

**Give your coding agent a map before it touches your code.**

`init-agent` is a local CLI that creates compact orientation packs for AI
coding agents. Instead of asking an agent to inspect an entire repository
blindly, it builds a local SQLite map of files, symbols, lightweight relations
and Git history, then suggests where the agent should start reading.

It does not call an LLM. It does not modify your source code. It uses Python
3.11+ and has no required external dependencies. Python files are parsed with
the standard-library `ast` module; PHP can optionally use tree-sitter for a
more precise graph.

## Why

Large repositories quickly become expensive and noisy for coding agents. Even
before editing code, an agent often needs to know which files are worth reading
first.

`init-agent` builds a local Project Orientation Layer so an agent can start
from a small, explainable context pack instead of reading the whole repo.

On a private PHP codebase with 274 indexed readable files:

- Full indexed project estimate: ~350,876 tokens
- Context pack for `login sessione admin`: ~839 tokens
- Estimated context pack + suggested first reads: ~3,050 tokens
- Estimated initial context reduction: ~99.1%

Token estimates use a simple `ceil(characters / 4)` heuristic.

## Real-World Comparison

An observed hidden-cause Django experiment compared two fresh agents on the same
task: one using normal repository exploration, one required to start with
`init-agent`.

Both agents passed the targeted test. On a 7,018-file Django checkout, the
init-agent-assisted run used fewer exploratory commands and less estimated
wall-clock time in the agent logs:

| Metric | Baseline | With init-agent |
|---|---:|---:|
| Approx logged wall-clock | ~8 min | ~1.5 min |
| Logged files read | 7 | 6 |
| Logged commands | 22 | 11 plus 5 init-agent commands |

This is an observed run, not a scientific benchmark. See
[experiments/django-hidden-cause](experiments/django-hidden-cause/) for the
task, prompts, logs and results.

## Install

Recommended install from GitHub:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
```

Then run:

```bash
init-agent --version
```

Optional PHP parsing upgrade:

```bash
pipx inject init-agent tree-sitter tree-sitter-php
```

With the optional extra installed, PHP mapping uses tree-sitter when available
and automatically falls back to the built-in parser when it is not.

If you do not have `pipx` installed:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

## Quick Start

Run it from the root of the project you want to orient:

```bash
cd your-project
init-agent run --overview --markdown
init-agent run "fix login session bug" --markdown
```

`run` automatically initializes `.agent/`, maps or refreshes the index, imports
Git metadata when available, and prints a compact context pack.

For a token estimate:

```bash
init-agent estimate "fix login session bug"
```

## Example Output

```text
# Init Agent Context Pack

Query: fix login session bug

## Suggested first reads
1. `src/auth/session.py`
   - score: 1.00
   - path matches "session"
   - symbol matches "session"
   - recently changed in query-related commit

2. `src/auth/login.py`
   - score: 0.84
   - filename matches "login"
   - calls "createSession"

## Related symbols
- `createSession` function in `src/auth/session.py:14`
- `loginUser` function in `src/auth/login.py:32`

## Useful follow-up commands
- `init-agent related src/auth/session.py`
- `init-agent callers createSession`
```

The output is orientation material. The agent should still read and verify the
suggested files before changing code.

## Use With Codex

Install the CLI once, then register the MCP server with Codex:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
init-agent mcp install-codex
```

This registers `init-agent` as a general Codex MCP server. It uses the current
Codex session working directory, so you do not need to reinstall it for every
repository. Use `--root /path/to/repo` only when you intentionally want to pin
the server to one repository.

You can also install the bundled Codex skill, which teaches Codex when to call
the CLI/MCP tools and how to verify the suggested files:

```bash
init-agent install-skill codex
```

Then open Codex from any repository and ask:

```text
Use the init-agent-orientation skill to orient yourself in this repository.
```

See [docs/mcp.md](docs/mcp.md) for MCP setup and
[skills/README.md](skills/README.md) for skill details and troubleshooting.

## Other Coding Agents

For Claude Code, Aider, OpenCode, Cursor-style terminals or other coding
agents, use the CLI directly and paste the Markdown output into the agent:

```bash
init-agent run --overview --markdown
init-agent run "your task or bug report" --markdown
```

Dedicated installers for other agents may be added after their instruction
formats and install locations are verified.

## What It Does

- Initializes a local `.agent/` workspace.
- Stores an interrogable SQLite index.
- Scans project files while skipping heavy directories, generated files and binaries.
- Detects likely language and file role.
- Extracts basic symbols from Python, PHP, JavaScript, TypeScript, Go and Rust.
- Extracts lightweight documentation, config and route signals.
- Records simple relations such as imports/includes, PHP function calls, file language and file role.
- Reads Git branch, status and recent commit timeline without modifying the repository.
- Produces terminal, JSON and Markdown context packs.
- Estimates token savings.

## What init-agent Is Not

- Not a coding agent.
- Not an LLM wrapper.
- Not a replacement for Codex, Claude Code, Aider, OpenCode or Pi.
- Not a semantic code analyzer.
- Not a documentation ingester that stores full prose.
- Not a tool that modifies your source code.

It is a local orientation layer that helps those tools start from better
context.

## Commands

| Command | Purpose |
|---|---|
| `init-agent run --overview --markdown` | Prepare and print a broad repository overview. |
| `init-agent run "<task>" --markdown` | Prepare and print a task-specific context pack. |
| `init-agent tool repo_graph_search --query "<task>" --json` | Agent-facing JSON search contract. |
| `init-agent tool repo_overview --json` | Agent-facing JSON repository overview contract. |
| `init-agent tool repo_entrypoints --json` | Agent-facing JSON entry-point discovery contract. |
| `init-agent tool repo_related_file --path <path> --json` | Agent-facing JSON file-neighborhood contract. |
| `init-agent tool repo_symbol_callers --symbol <name> --json` | Agent-facing JSON symbol caller contract. |
| `init-agent tool repo_feedback_add --query "<task>" --path <path> --rating useful --json` | Record optional local feedback after verification. |
| `init-agent tool repo_memory_add --path <path> --note "..." --json` | Record an optional local note about a verified file. |
| `init-agent tool repo_memory_add --scope repo --note "..." --json` | Record an optional repo-wide project note. |
| `init-agent tool repo_memory_audit --json` | Audit local memory quality. |
| `init-agent tool repo_session_summary --json` | Summarize local handoff metadata after an agent session. |
| `init-agent session close` | Print an end-of-session checklist for handoff. |
| `init-agent tool repo_memory_topics --json` | Summarize local memory by topic/area. |
| `init-agent tool repo_memory_update --id <id> --note "..." --json` | Refresh or replace an existing local note. |
| `init-agent tool repo_memory_list --stale --json` | Audit local notes, including stale notes. |
| `init-agent tool repo_task_add --title "..." --json` | Track an open local task/session item linked to files and checks. |
| `init-agent tool repo_task_note --id <id> --note "..." --json` | Append progress, files, tests or remaining work to a local task. |
| `init-agent tool repo_task_close --id <id> --json` | Mark a local task/session item done. |
| `init-agent mcp` | Run the local MCP stdio wrapper for repo tool contracts. |
| `init-agent mcp install-codex` | Register init-agent MCP with Codex through `codex mcp add`. |
| `init-agent mcp uninstall-codex` | Remove init-agent MCP from Codex through `codex mcp remove`. |
| `init-agent estimate "<task>"` | Estimate context savings. |
| `init-agent export --json` | Export the local graph metadata for external tools. |
| `init-agent doctor` | Check local index health. |
| `init-agent symbol <name>` | Show symbol definitions, callers and candidate files. |
| `init-agent callers <name>` | Show files that call a symbol/function. |
| `init-agent related <path>` | Show symbols, relations and commits around one file. |
| `init-agent feedback add ...` | Store local ranking feedback after verification. |

See [docs/commands.md](docs/commands.md) for the full command reference.

See [docs/mcp.md](docs/mcp.md) for MCP setup and Codex configuration examples.
See [docs/memory-workflows.md](docs/memory-workflows.md) for decision-log and
area-map memory patterns.
See [docs/parsing.md](docs/parsing.md) for Python AST parsing and optional PHP
tree-sitter setup.

## Feedback

Agents can record local feedback after verifying files:

```bash
init-agent feedback add "fix login session bug" src/auth/session.py --rating useful --source agent
init-agent feedback explain "fix login session bug"
```

Feedback stays local in `.agent/graph.sqlite`. It is a bounded ranking signal,
not training data and not a source of truth.

MCP-capable agents can also use `repo_feedback_add` and
`repo_feedback_explain` directly after verifying files. This lets an agent
record that a file was useful, noisy, or missing from the initial pack without
making feedback mandatory.

See [docs/feedback.md](docs/feedback.md) for details.

Agents can also store short local file notes after understanding code:

```bash
init-agent tool repo_memory_add --path src/auth/session.py --topic "login session" --evidence read_full_file --note "Session validation lives here; verified during redirect debugging." --json
init-agent tool repo_memory_add --scope repo --topic "architecture" --evidence user_decision --note "Use a local-only CLI with SQLite storage." --json
init-agent tool repo_memory_search --query "login session validation" --json
init-agent tool repo_memory_audit --json
init-agent tool repo_memory_topics --topic "login session" --json
init-agent tool repo_memory_list --stale --json
init-agent tool repo_memory_update --id 12 --evidence read_full_file --note "Session validation lives here; refreshed after re-reading the file." --json
```

This is local working memory, not model training and not a replacement for
reading files before editing. Memory results include a stale flag when the
indexed file hash changed after the note was recorded. Notes also include an
evidence field so agents can distinguish full-file reads, excerpts, manifest
checks, graph-only inferences, user decisions, implementation notes and
planning notes. Repo-wide memories are not tied to a file hash and report stale
status as not applicable. They can be recorded before the first `init-agent map`
when a project starts from an empty directory; keep them small and factual.
For practical decision-log and area-map patterns, see
[docs/memory-workflows.md](docs/memory-workflows.md).

For longer work, agents can also track a local task/session item:

```bash
init-agent tool repo_task_add --title "Fix login redirect" --topic auth --file src/auth/session.py --status in_progress --json
init-agent tool repo_task_note --id 1 --note "Verified session handling; redirect smoke check remains." --file src/auth/login.py --test "python -m unittest discover -s tests" --remaining "Run manual redirect smoke check." --json
init-agent tool repo_task_close --id 1 --summary "Login redirect task completed." --json
```

Tasks are local operational memory. They are useful for handoff and session
continuity, but they are not a replacement for GitHub Issues or project
management tools.

## Validation

This repository includes unit tests and a local experiment runner covering
multiple real-world repositories and counter-cases:

```bash
python -m unittest discover -s tests -v
python experiments/evaluate.py --strict
python experiments/evaluate.py --strict --output-dir experiments/results
python experiments/plot_results.py experiments/results/results.csv
```

The deterministic benchmark measures repository-orientation quality: whether
expected useful files appear early in the generated context pack. It can write
JSON, CSV and Markdown summaries, plus optional charts. See
[docs/experiments.md](docs/experiments.md) for benchmark setup and output.

## Security And Privacy

- Local only.
- No LLM calls.
- No external services contacted by the CLI.
- No full source code stored in SQLite.
- Generated indexes live under `.agent/` and should usually stay ignored.

File contents may be read locally during mapping, refresh and token estimation
to extract lightweight metadata, symbols, hashes and character counts.

See [docs/security.md](docs/security.md) for details.

## Current Limits

- Symbol extraction is intentionally shallow. Python uses `ast`; PHP uses an
  optional tree-sitter parser when installed, otherwise it falls back to the
  built-in regex parser.
- Import/include resolution is best-effort.
- Context ranking is heuristic and may surface relevant-looking but non-essential files.
- Entrypoint discovery is heuristic and may miss custom boot files or include support files.
- Context packs are a starting point, not a source of truth.
- Refresh is incremental by file hash, but it does not yet do dependency-aware cascading updates.
- No built-in LLM execution.
- No graph visualization yet.

## Roadmap

- More precise entrypoint classification for frontend, deploy, docs and custom PHP projects.
- Better filtering of barrel/type/schema files from runtime entrypoint results.
- MCP and skill installers for additional agent runtimes after their formats are verified.
- Link chat and agent sessions to repository context packs.
- Dependency-aware incremental updates.
- Graph visualization.
- Language and framework plugin support.
- Broader optional tree-sitter support for languages where the standard library
  does not provide a reliable parser.

## Development

For local development from a checkout:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

Run the CLI without installing:

```bash
python -m init_agent.cli --help
```

More documentation:

- [Agent usage](docs/agent-usage.md)
- [Command reference](docs/commands.md)
- [Parsing and optional tree-sitter](docs/parsing.md)
- [Scoring](docs/scoring.md)
- [Feedback](docs/feedback.md)
- [Memory workflows](docs/memory-workflows.md)
- [Validation experiments](docs/experiments.md)
- [Security and privacy](docs/security.md)
