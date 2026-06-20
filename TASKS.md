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
- [x] Add benchmark cases from a private PHP codebase for procedural calls, discussion helpers and CRUD builder helpers.

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
- [x] Add a private PHP optional local benchmark path, skipped when absent.
- [x] Track per-case failure notes for known weak areas such as Vue compiler transforms.
- [x] Add elapsed-time comparison between manual broad scan estimates and init-agent context generation.

## Phase 5: Agent Skill Packaging

- [x] Update the `init-agent-orientation` skill to route agent questions through `run`, `symbol`, `callers` and `related` automatically.
- [x] Create a minimal `init-agent-orientation` skill template in the repo.
- [x] Document shim installation for local development.
- [x] Add troubleshooting for `init-agent: command not found`.
- [x] Add a copy-paste workflow for Codex, Claude Code, Aider and similar CLI agents.

## Phase 6: Repository Overview Mode

- [ ] Add `init-agent overview` or `init-agent run --overview` for broad repository orientation.
- [ ] Prefer manifest and entry-point files for overview queries: `pyproject.toml`, `package.json`, `composer.json`, `go.mod`, `Cargo.toml`, README, CLI modules, server/app modules, router files and config files.
- [ ] Reduce noise from generic overview words such as `architecture`, `backend`, `frontend`, `test`, `entry point` when they are not specific enough.
- [ ] Return a compact overview pack with likely entry points, major subsystems, package manifests and first files to read.
- [ ] Add benchmark cases for general orientation on `init-agent`, OpenJarvis-style Python/frontend repos and at least one PHP repo.
- [ ] Update `init-agent-orientation` skill to use overview mode before falling back to refined `run` queries.
- [ ] Document clearly that overview is still heuristic and must be verified by reading files.

## Phase 7: Public Release Readiness

- [ ] Review `.gitignore` for generated indexes, build output and local benchmark folders.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 experiments/evaluate.py --strict`.
- [ ] Run `init-agent doctor` on this repository.
- [ ] Re-read README first screen for clarity.
- [ ] Tag a release only after a clean git status and a fresh install test.
