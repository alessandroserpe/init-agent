# init-agent

[![CI](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/alessandroserpe/init-agent/actions/workflows/ci.yml)

**Give your coding agent a map before it touches your code.**

`init-agent` is a local CLI, SQLite index and MCP server for repository
orientation. It helps coding agents decide where to start reading, remember
verified local context, and leave an inspectable trail of what was useful,
noisy or missing.

It does not call an LLM. It does not edit source code. It stores local metadata
under `.agent/` and keeps source contents out of the SQLite index.

## Why

Coding agents often spend a lot of context just finding the right files. In a
large or legacy repository, the first problem is not always "write the patch";
it is "where does this behavior live?"

`init-agent` gives the agent a local Project Orientation Layer:

- a compact repository overview;
- resolved runtime-flow edges for imports, includes, calls, routes and templates;
- task-specific context packs;
- reading plans with a bounded first-read budget;
- feedback for verified useful, noisy or missing files;
- short local memory notes with stale checks;
- local task/session handoff metadata;
- a read-only dashboard for humans.

The output is orientation material, not source of truth. Agents should still
read and verify files before changing code.

## Install

Recommended install from GitHub:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
init-agent --version
```

After upgrading an existing installation, synchronize copied Codex assets:

```bash
pipx upgrade init-agent
init-agent sync
```

`sync` updates the bundled Codex skill, backs up locally modified skill files,
and reports whether the init-agent MCP server is registered. It does not edit
Codex MCP configuration.

If you do not have `pipx`:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Optional PHP parsing upgrade:

```bash
pipx inject init-agent tree-sitter tree-sitter-php
```

With the optional packages installed, PHP mapping uses tree-sitter when
available and falls back to the built-in parser otherwise. Python parsing uses
the standard-library `ast` module.

## Quick Start

Run from the root of the project you want to inspect:

```bash
init-agent run --overview --markdown
init-agent run "fix login session bug" --markdown
```

For day-to-day agent work, prefer the smaller loop:

```bash
init-agent plan "fix login session bug" --read 3
# read and verify the suggested files
init-agent plan read --id <id> --file <path> --note "opened while investigating"
init-agent plan finish --id <id> --read-file <path> --verified <path> --central <path> --support <path> --summary "short outcome"
init-agent session close
```

For a human-readable local dashboard:

```bash
init-agent web
```

The dashboard is read-only and shows local memory, feedback, open tasks,
reading plans, orientation scorecard metrics and recurring files.

For larger plans, `init-agent` can also return conservative delegation advice.
It may propose bounded read-only workstreams with `fast`, `balanced` or `deep`
model tiers and a reasoning-effort hint. The coding agent remains the
orchestrator: it decides whether to delegate, every worker must submit a
structured report, and the parent must review that report before finishing the
plan. `init-agent` does not launch agents or choose provider-specific models.

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

## Useful follow-up commands
- `init-agent related src/auth/session.py`
- `init-agent callers createSession`
```

## Core Workflow

You do not need to remember every command. The recommended daily workflow is:

| Step | Command | Use when |
|---|---|---|
| Orient | `init-agent overview` | You are new to a repository. |
| Plan | `init-agent plan "<task>" --read 3` | You are about to inspect or change code. |
| Verify | read files directly | The context pack only suggests where to look. |
| Close loop | `init-agent plan finish --id <id> ...` | You know what was useful, noisy or missing. |
| Handoff | `init-agent session close` | You are wrapping up work. |
| Observe | `init-agent web` | A human wants a local dashboard. |

Useful follow-ups:

- `init-agent trace "<task>"` for runtime paths and entrypoint flows.
- `init-agent related <path>` for a file neighborhood.
- `init-agent symbol <name>` and `init-agent callers <name>` for symbols.
- `init-agent scorecard` for local orientation quality metrics.
- `init-agent estimate "<task>"` for rough context-size estimates.

See [docs/commands.md](docs/commands.md) for the full command reference.

For MCP and scripted integrations, the same loop is available through JSON
tools such as `repo_reading_plan_read`, `repo_reading_plan_diff`,
`repo_reading_plan_finish`, `repo_workstream_report`,
`repo_workstream_review`, `repo_task_note` and `repo_task_close`.

## Use With Codex

Install the CLI once, then register the MCP server with Codex:

```bash
pipx install git+https://github.com/alessandroserpe/init-agent.git
init-agent mcp install-codex
```

This registers `init-agent` as a general Codex MCP server. It uses the current
Codex session working directory, so you do not need to reinstall it for every
repository.

You can also install the bundled Codex skill:

```bash
init-agent install-skill codex
```

`init-agent doctor` detects an installed skill that differs from the bundled
version without using the network. To explicitly check GitHub for a newer
init-agent release, run `init-agent doctor --check-updates`.

Then open Codex from a repository and ask:

```text
Use the init-agent-orientation skill to orient yourself in this repository.
```

See [docs/mcp.md](docs/mcp.md), [docs/agent-usage.md](docs/agent-usage.md) and
[skills/README.md](skills/README.md) for details.

## Memory, Feedback And Tasks

`init-agent` can store optional local metadata after verification:

- feedback: a file was useful, noisy or missing for a task;
- memory: a short fact about a file or repository decision;
- tasks: lightweight local session items and handoff notes;
- plan events: what the agent planned, read and verified.

These records stay in `.agent/graph.sqlite`. They are not training data and do
not replace direct file reads. File-scoped memory stores hashes so stale notes
can be detected after code changes.

See:

- [docs/feedback.md](docs/feedback.md)
- [docs/memory-workflows.md](docs/memory-workflows.md)
- [docs/agent-usage.md](docs/agent-usage.md)
- [docs/parsing.md](docs/parsing.md)

## Validation

The repository includes tests and an orientation benchmark runner:

```bash
python -m unittest discover -s tests -v
python experiments/evaluate.py --strict --min-cases 4
python experiments/flow-graph/evaluate.py --strict --min-resolution-rate 1.0
python experiments/evaluate.py --strict --min-cases 4 --output-dir experiments/results
python experiments/plot_results.py experiments/results/results.csv
```

The deterministic benchmarks measure repository-orientation quality and graph
quality separately: whether expected files appear early, whether extracted
runtime relations resolve to real repository files, and whether resolution
adds ranking noise. They are not end-to-end benchmarks of agent speed or patch
quality.

Observed paired agent runs, including a Django hidden-cause experiment, live in
the `experiments/` directory. They are useful workflow evidence, not broad
performance claims. See [docs/experiments.md](docs/experiments.md).

## Security And Privacy

- Local only.
- No LLM calls.
- No external services contacted by the CLI.
- No full source code stored in SQLite.
- Generated indexes live under `.agent/` and should usually stay ignored.

File contents may be read locally during mapping, refresh and token estimation
to extract lightweight metadata, symbols, hashes and character counts.

See [docs/security.md](docs/security.md).

## Current Limits

- Ranking is heuristic and may surface relevant-looking but non-essential files.
- Symbol extraction remains intentionally lightweight and local.
- Raw relations are preserved; imports, includes, calls, routes and templates
  are resolved to concrete files only when the target is unambiguous.
- Entrypoint discovery may miss custom boot files.
- Refresh is incremental by file hash, but not dependency-aware.
- No built-in LLM execution.
- The web dashboard does not yet render an interactive symbol/relation graph.

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
- [MCP integration](docs/mcp.md)
- [Parsing and optional tree-sitter](docs/parsing.md)
- [Scoring](docs/scoring.md)
- [Feedback](docs/feedback.md)
- [Memory workflows](docs/memory-workflows.md)
- [Validation experiments](docs/experiments.md)
- [Roadmap](docs/roadmap.md)
- [Security and privacy](docs/security.md)
