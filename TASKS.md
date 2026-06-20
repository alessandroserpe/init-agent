# init-agent Task Plan

This file tracks the next implementation steps for making `init-agent` more useful as a local Project Orientation Layer.

## Principles

- Keep the database metadata-first; do not store full source files.
- Prefer general heuristics over project-specific hardcoding.
- Add benchmark cases before or with scoring changes.
- Treat context packs as orientation, not source of truth.
- Verify every meaningful change with unit tests and `experiments/evaluate.py --strict`.

## Phase 1: PHP Call Graph Quality

- [ ] Expand PHP builtin/function exclusions for noisy calls such as `mysqli_query`, `htmlspecialchars`, `trim`, `json_decode`, `file_exists`, `count`, `in_array`, `array_map`, `date`, `time`.
- [ ] Store call counts per `(source file, target symbol name)` or expose aggregated counts in `related`.
- [ ] Add `init-agent callers <symbol>` to show files that call a function name.
- [ ] Add `init-agent symbol <symbol>` to show definitions, callers, candidate files and recent commits for a symbol.
- [ ] Add benchmark cases from `fc5` for `creaForm`, `aggiornaForm`, discussion helpers and CRUD builder helpers.

## Phase 2: Documentation And Config Extraction

- [ ] Extract Markdown headings as `heading` symbols.
- [ ] Extract README command blocks as lightweight `command_example` symbols without storing full prose.
- [ ] Extract top-level JSON/TOML/YAML keys as config symbols.
- [ ] Extract package scripts from `package.json`.
- [ ] Extract project scripts/entry points from `pyproject.toml`.

## Phase 3: Framework-Aware Signals

- [ ] Add lightweight route extraction for PHP route patterns when present.
- [ ] Add Express/Fastify route extraction.
- [ ] Add Flask/Django URL/route extraction.
- [ ] Add Gin route extraction.
- [ ] Keep framework extractors optional and regex-light unless a parser is introduced.

## Phase 4: Benchmark Hardening

- [ ] Add a benchmark case runner filter: `experiments/evaluate.py --case <name>`.
- [ ] Add benchmark setup notes for cloning required repositories.
- [ ] Add `fc5` as an optional local benchmark path, skipped when absent.
- [ ] Track per-case failure notes for known weak areas such as Vue compiler transforms.
- [ ] Add elapsed-time comparison between manual broad scan estimates and init-agent context generation.

## Phase 5: Agent Skill Packaging

- [ ] Create a minimal `init-agent-orientation` skill template in the repo.
- [ ] Document shim installation for local development.
- [ ] Add troubleshooting for `init-agent: command not found`.
- [ ] Add a copy-paste workflow for Codex, Claude Code, Aider and similar CLI agents.

## Phase 6: Public Release Readiness

- [ ] Review `.gitignore` for generated indexes, build output and local benchmark folders.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 experiments/evaluate.py --strict`.
- [ ] Run `init-agent doctor` on this repository.
- [ ] Re-read README first screen for clarity.
- [ ] Tag a release only after a clean git status and a fresh install test.
