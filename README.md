# init-agent

[![CI](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml)

**Give your coding agent a map before it touches your code.**

`init-agent` is a local CLI that creates compact orientation packs for AI
coding agents. Instead of asking an agent to inspect an entire repository
blindly, it builds a local SQLite map of files, symbols, lightweight relations
and Git history, then suggests where the agent should start reading.

It does not call an LLM. It does not modify your source code. It uses Python
3.11+ and has no required external dependencies.

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

## Install

Recommended install from GitHub:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
```

Then run:

```bash
init-agent --version
```

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

## Optional: Codex Skill

Install the CLI, then install the bundled Codex skill:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
init-agent install-skill codex
```

Then open Codex from any repository and ask:

```text
Use the init-agent-orientation skill to orient yourself in this repository.
```

See [skills/README.md](skills/README.md) for skill details and troubleshooting.

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
| `init-agent estimate "<task>"` | Estimate context savings. |
| `init-agent doctor` | Check local index health. |
| `init-agent symbol <name>` | Show symbol definitions, callers and candidate files. |
| `init-agent callers <name>` | Show files that call a symbol/function. |
| `init-agent related <path>` | Show symbols, relations and commits around one file. |
| `init-agent feedback add ...` | Store local ranking feedback after verification. |

See [docs/commands.md](docs/commands.md) for the full command reference.

## Feedback

Agents can record local feedback after verifying files:

```bash
init-agent feedback add "fix login session bug" src/auth/session.py --rating useful --source agent
init-agent feedback explain "fix login session bug"
```

Feedback stays local in `.agent/graph.sqlite`. It is a bounded ranking signal,
not training data and not a source of truth.

See [docs/feedback.md](docs/feedback.md) for details.

## Validation

This repository includes unit tests and a local experiment runner covering
multiple real-world repositories and counter-cases:

```bash
python -m unittest discover -s tests -v
python experiments/evaluate.py --strict
```

See [docs/experiments.md](docs/experiments.md) for benchmark setup and output.

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

- Symbol extraction is regex-based and intentionally shallow.
- Import/include resolution is best-effort.
- Context ranking is heuristic and may surface relevant-looking but non-essential files.
- Context packs are a starting point, not a source of truth.
- Refresh is incremental by file hash, but it does not yet do dependency-aware cascading updates.
- No built-in LLM execution.
- No graph visualization yet.

## Roadmap

- JSON graph export for external tools and visualization.
- Tool `repo_graph_search` for agent runtimes.
- Link chat and agent sessions to repository context packs.
- Dependency-aware incremental updates.
- Language and framework plugin support.
- Optional tree-sitter support for more precise parsing.

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
- [Scoring](docs/scoring.md)
- [Feedback](docs/feedback.md)
- [Validation experiments](docs/experiments.md)
- [Security and privacy](docs/security.md)
