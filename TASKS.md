# init-agent Task Plan

This file tracks the next implementation steps for making `init-agent` more useful as a local Project Orientation Layer.

## Principles

- Keep the database metadata-first; do not store full source files.
- Prefer general heuristics over project-specific hardcoding.
- Add benchmark cases before or with scoring changes.
- Treat context packs as orientation, not source of truth.
- Verify every meaningful change with unit tests and `experiments/evaluate.py --strict`.

## Phase 1: PHP Call Graph Quality

- [x] Expand PHP builtin/function exclusions for noisy calls such as `mysqli_query`, `htmlspecialchars`, `trim`, `json_decode`, `file_exists`, `count`, `in_array`, `array_map`, `date`, `time`.
- [x] Store call counts per `(source file, target symbol name)` or expose aggregated counts in `related`.
- [x] Add `init-agent callers <symbol>` to show files that call a function name.
- [x] Add `init-agent symbol <symbol>` to show definitions, callers, candidate files and recent commits for a symbol.
- [x] Add benchmark coverage for procedural PHP call-graph behavior.

## Phase 2: Documentation And Config Extraction

- [x] Extract Markdown headings as `heading` symbols.
- [x] Extract README command blocks as lightweight `command_example` symbols without storing full prose.
- [x] Extract top-level JSON/TOML/YAML keys as config symbols.
- [x] Extract package scripts from `package.json`.
- [x] Extract project scripts/entry points from `pyproject.toml`.

## Phase 3: Framework-Aware Signals

- [x] Add lightweight route extraction for PHP route patterns when present.
- [x] Add Express/Fastify route extraction.
- [x] Add Flask/Django URL/route extraction.
- [x] Add Gin route extraction.
- [x] Keep framework extractors optional and regex-light unless a parser is introduced.

## Phase 4: Benchmark Hardening

- [x] Add a benchmark case runner filter: `experiments/evaluate.py --case <name>`.
- [x] Add benchmark setup notes for cloning required repositories.
- [x] Keep optional local benchmark repositories skipped when absent.
- [x] Track per-case failure notes for known weak areas such as Vue compiler transforms.
- [x] Add elapsed-time comparison between manual broad scan estimates and init-agent context generation.

## Phase 5: Agent Skill Packaging

- [x] Update the `init-agent-orientation` skill to route agent questions through `run`, `symbol`, `callers` and `related` automatically.
- [x] Create a minimal `init-agent-orientation` skill template in the repo.
- [x] Document shim installation for local development.
- [x] Add troubleshooting for `init-agent: command not found`.
- [x] Add a copy-paste workflow for Codex, Claude Code, Aider and similar CLI agents.

## Phase 6: Repository Overview Mode

- [x] Add `init-agent overview` or `init-agent run --overview` for broad repository orientation.
- [x] Prefer manifest and entry-point files for overview queries: `pyproject.toml`, `package.json`, `composer.json`, `go.mod`, `Cargo.toml`, README, CLI modules, server/app modules, router files and config files.
- [x] Reduce noise from generic overview words such as `architecture`, `backend`, `frontend`, `test`, `entry point` when they are not specific enough.
- [x] Return a compact overview pack with likely entry points, major subsystems, package manifests and first files to read.
- [x] Add benchmark cases for general orientation on `init-agent`, Python/frontend repos and at least one PHP repo.
- [x] Update `init-agent-orientation` skill to use overview mode before falling back to refined `run` queries.
- [x] Document clearly that overview is still heuristic and must be verified by reading files.

Follow-up ideas:

- [x] Improve Python framework overview entry-point hints, for example Django management modules such as `django/core/management/__init__.py`.
- [x] Reduce documentation noise in operational TypeScript/monorepo queries when the query is not docs-aware, for example Vite dependency optimizer context.
- [x] Improve Python tooling queries where words such as `setup` can refer to runtime flow as well as tests or helpers, for example pytest fixture setup planning.

## Phase 7: Local Orientation Feedback

- [x] Add a local `orientation_feedback` table for query/file/rating/reason/source metadata.
- [x] Add `init-agent feedback add` to let an agent mark files as `crucial`, `useful`, `neutral`, `noisy` or `missing` for a query.
- [x] Add `init-agent feedback import --json` for agent-produced feedback batches.
- [x] Use feedback as a bounded ranking signal without letting old feedback dominate direct path/symbol matches.
- [x] Show transparent reasons such as `previously marked useful for similar query`.
- [x] Keep feedback local, inspectable and deletable; do not store full source code.
- [x] Add tests proving feedback improves repeated similar queries and does not overfit unrelated queries.
- [x] Update the `init-agent-orientation` skill so agents can record feedback after verifying files.

Follow-up ideas:

- [x] Add feedback similarity diagnostics so agents can inspect why a feedback item matched a query.
- [x] Add optional feedback decay or weighting by source after enough real agent sessions.

## Phase 8: Public Release Readiness

- [x] Review `.gitignore` for generated indexes, build output and local benchmark folders.
- [x] Run `python3 -m unittest discover -s tests -v`.
- [x] Run `python3 experiments/evaluate.py --strict`.
- [x] Run `init-agent doctor` on this repository.
- [x] Re-read README first screen for clarity.
- [x] Tag a release only after a clean git status and a fresh install test.

## Phase 9: Public Project Hardening

- [x] Add GitHub Actions CI for supported Python versions.
- [ ] Add a README badge once the first GitHub Actions run is green.
- [x] Document `pipx` installation directly from GitHub.
- [ ] Add compact public example workflows for coding agents.
- [ ] Improve `run --markdown` output for agent handoff use cases.
- [ ] Document the feedback loop as an agent workflow: run, verify, record feedback, explain feedback.
- [ ] Add `init-agent export --json` for external tools and future graph visualization.
- [ ] Add a lightweight issue template for bug reports and noisy-ranking reports.
- [ ] Evaluate whether PyPI publishing is worth doing after external install testing.
