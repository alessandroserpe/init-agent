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

## Phase 7b: Local Agent File Memory

- [x] Add local agent notes tied to project-relative file paths.
- [x] Expose memory tools through CLI and MCP: `repo_memory_add`, `repo_memory_search`, `repo_file_notes`.
- [x] Keep notes short, factual and local; do not store full source snippets.
- [x] Store the indexed file hash with each note and mark notes stale when the file changes.
- [x] Add evidence levels so agents can distinguish full-file reads, excerpts, manifest checks and graph-only inferences.
- [x] Add memory management tools for listing stale notes and deleting wrong or duplicate notes.
- [x] Add a memory update command after real usage showed the replacement semantics.
- [ ] Consider explicit memory supersede links only if update/delete are not enough.
- [x] Add topic-level aggregate memories for repository areas such as server startup, frontend boot or routing.
- [ ] Consider scope levels for notes: repo-wide, file-specific and symbol-specific.
- [ ] Add memory clear/export/import commands if real usage shows notes accumulating too quickly.
- [ ] Consider summarizing repeated notes per file only after enough real agent sessions.

## Phase 7d: Memory Quality And Area Workflows

Priority order:

- [x] Add `repo_memory_audit` to report stale notes, unknown evidence, missing topics, likely duplicates and overly short notes.
- [x] Document decision-log and area-map workflows using repo-scoped memories and `repo_memory_topics`.
- [x] Add a lightweight end-of-task reminder so agents consider memory/feedback after verification.
- [x] Add lightweight session summary support as local handoff metadata without persistent session tracking.
- [ ] Consider task memory linked to files/topics only if notes plus decision-log are not enough.
- [ ] Avoid turning init-agent into a generic project manager; keep features repository-oriented and metadata-first.

## Phase 7c: Project Memory For Empty Repositories

- [x] Add repo-wide memories for projects that start from zero before meaningful files exist.
- [x] Support memory scope values such as `repo`, `file` and later possibly `symbol`.
- [x] Make `path` optional for repo-wide memories while keeping file memories tied to project-relative paths.
- [x] Add evidence values for project decisions, such as `user_decision`, `implementation_note` and `planning_note`.
- [x] Treat repo-wide memory staleness as not applicable instead of file-hash based.
- [x] Let agents record short architecture decisions, conventions, created-file intent and test commands during project creation.
- [x] Keep repo-wide memory intentionally small so it supports coherence without becoming a project-management system.

## Phase 8: Public Release Readiness

- [x] Review `.gitignore` for generated indexes, build output and local benchmark folders.
- [x] Run `python3 -m unittest discover -s tests -v`.
- [x] Run `python3 experiments/evaluate.py --strict`.
- [x] Run `init-agent doctor` on this repository.
- [x] Re-read README first screen for clarity.
- [x] Tag a release only after a clean git status and a fresh install test.

## Phase 9: Public Project Hardening

- [x] Add GitHub Actions CI for supported Python versions.
- [x] Make `experiments/evaluate.py --strict` pass in CI without requiring optional external benchmark repositories.
- [x] Add a README badge once the first GitHub Actions run is green.
- [x] Document `pipx` installation directly from GitHub.
- [x] Add compact public example workflows for coding agents.
- [x] Improve `run --markdown` output for agent handoff use cases.
- [x] Add `init-agent install-skill codex` to install/update the bundled Codex skill from the installed package.
- [x] Document verified Codex installation separately from generic Markdown workflows for other agents.
- [x] Split the long README into a product-first entry page plus focused `docs/` references.
- [x] Document the feedback loop as an agent workflow: run, verify, record feedback, explain feedback.
- [ ] Investigate Claude Code's supported instruction format before adding a dedicated `install-skill claude-code` command.
  Deferred until a Claude Code environment or user can verify install paths, reload behavior and expected instruction format; use the generic Markdown/MCP workflow in the meantime.
- [x] Add a lightweight issue template for bug reports and noisy-ranking reports.
- [ ] Evaluate whether PyPI publishing is worth doing after external install testing.

## Phase 10: Next Architecture Priorities

- [x] Add `init-agent export --json` for external tools and future graph visualization.
- [x] Design `repo_graph_search` as an agent-facing CLI tool with a stable JSON contract.
- [x] Add `repo_overview`, `repo_related_file` and `repo_symbol_callers` CLI tool contracts before MCP.
- [x] Expose the repo tool contracts through a minimal MCP stdio server.
- [x] Add verified Codex MCP configuration examples for `config.toml`.
- [x] Test Codex MCP loading in a fresh session and document any client-specific caveats.
- [ ] Link chat and agent sessions to repository context packs, including verified files and useful/noisy feedback.
- [ ] Add dependency-aware refresh so related files can be marked stale or re-ranked when an upstream include/import changes.
- [ ] Design language and framework plugin support so new extractors can be added without bloating the core.
- [ ] Evaluate optional tree-sitter support for more precise parsing while keeping the default install dependency-light.
