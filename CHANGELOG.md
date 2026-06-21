# Changelog

All notable changes to `init-agent` are documented here.

## Unreleased

- Added GitHub Actions CI for Python 3.11, 3.12 and 3.13.
- Made benchmark strict mode usable in CI by falling back to the current checkout for the init-agent overview case.
- Documented `pipx` installation directly from GitHub.
- Added the next public hardening tasks to the project task plan.
- Improved `run --markdown` handoff output with follow-up commands and safety notes for coding agents.
- Added `init-agent install-skill codex` to install or update the bundled Codex skill from a normal package installation.
- Documented the two-command Codex setup path prominently in the README.
- Clarified that non-Codex agents should use the Markdown workflow until their native skill formats are verified.

## 0.15.0

- Improved filename matching for compound filenames, for example matching `setup` inside `setupplan.py`.
- Improved Python tooling context for pytest-style fixture setup planning without adding project-specific rules.
- Added bounded feedback source weighting so user and benchmark feedback can carry slightly more weight than agent feedback.

## 0.14.4

- Reduced documentation ranking noise in operational context queries by applying a stronger documentation penalty when the query is not docs-aware.
- Kept docs-aware queries such as `docs ... guide` explicitly preferred for README and guide files.

## 0.14.3

- Improved repository overview detection for Python framework package entry points such as `management`, `commands`, `cli`, `server`, `api`, `routing`, `routes` and `urls` package initializers.
- Added regression coverage so framework package entry points are surfaced ahead of matching tests or docs.

## 0.14.2

- Added `init-agent feedback explain <query>` to inspect which local feedback items affect a query.
- Added JSON explain output with query tokens, similarity, score contribution, matched signals and ignored feedback entries.
- Updated the orientation skill guidance so agents can diagnose feedback before trusting or adding more of it.

## 0.14.1

- Stronger demotion for files previously marked `noisy` by local orientation feedback.
- Stronger bounded boost for files previously marked `crucial` or `useful`, while preserving heuristic ranking rather than enforcing absolute positions.
- Feedback scoring now runs after role/type adjustments so verified noise is not diluted before final ranking.

## 0.14.0

- Added local `init-agent feedback` commands for agent/user/benchmark feedback.
- Added an `orientation_feedback` SQLite table for query, path, rating, reason and source metadata.
- Context scoring now applies bounded feedback boosts and penalties for similar queries.
- Feedback reasons are transparent in context packs, for example `previously marked useful for similar query`.
- Added JSON export/import for local feedback data.

## 0.13.0

- Added `init-agent overview` for broad repository orientation from indexed metadata.
- Added `init-agent run --overview` so agents can prepare a project and get a broad overview in one command.
- Overview mode prioritizes manifests, README/config files, likely entry points, route files, scripts and major subsystems.
- Updated the `init-agent-orientation` skill template to use overview mode for broad repository questions.

## 0.12.0

- Added a versioned `init-agent-orientation` skill template for coding agents.
- Documented Codex skill installation, local shim setup and troubleshooting.
- Added a copy-paste workflow for Codex, Claude Code, Aider, OpenCode and similar CLI agents.
- Updated README guidance for agent-oriented use of `run`, `symbol`, `callers` and `related`.

## 0.11.1

- Added `experiments/evaluate.py --case <name>` for isolating individual benchmark cases.
- Added optional broad indexed-file read timing with `--measure-manual-scan`.
- Added benchmark setup notes and per-case notes for known weak areas.
- Added benchmark summary fields for candidate count, indexed-file count and scan reduction.

## 0.11.0

- Added lightweight route extraction as `route` symbols for common PHP route patterns.
- Added Express/Fastify route extraction and `route_to_handler` relations when handlers are recognizable.
- Added Flask/Django route extraction.
- Added Gin route extraction.
- Bumped the internal index version so existing projects rebuild with route metadata.

## 0.10.0

- Extracted Markdown headings as lightweight `heading` symbols.
- Extracted README fenced command lines as `command_example` symbols without storing full prose.
- Extracted top-level JSON/TOML/YAML keys as `config_key` symbols.
- Extracted `package.json` scripts and `pyproject.toml` project scripts/entry points.
- Bumped the internal index version so existing projects rebuild with the new extractor.

## 0.9.2

- Added internal index versioning so `run` rebuilds stale indexes after extractor changes instead of trusting unchanged file hashes.
- `refresh` and `doctor` now report stale indexes clearly and suggest `init-agent map`.
- `run`, `context`, `query` and `estimate` now accept unquoted multi-word queries.

## 0.9.1

- Expanded PHP builtin exclusions so common runtime/helper calls do not dominate call graph output.
- Added `init-agent callers <symbol>` to show definitions and files that call a function or symbol name.
- Added `init-agent symbol <symbol>` to show definitions, callers, candidate files and recent commits for a symbol.
- Aggregated caller output with call counts and first call line per file.
- Added local benchmark coverage for procedural PHP call graph orientation.

## 0.9.0

- Added conservative PHP global function call extraction as `calls` relations.
- Context scoring now uses PHP `calls` relations when a query matches a called function name.
- `init-agent related <path>` now shows resolved PHP calls and files that call symbols defined in the selected file.
- Added tests for PHP procedural flow such as `index.php -> bootstrap.php -> functions.php`.

## 0.8.7

- Excluded Python packaging metadata directories such as `*.egg-info` and `*.dist-info` from indexing.
- Added regression tests so `map`, `refresh` and `doctor` share the same packaging metadata ignore behavior.

## 0.8.6

- Added benchmark coverage for pytest and Vue Core, plus counter-cases where docs, examples and CSS are intentionally relevant.
- Added `experiments/evaluate.py --rebuild-index` to rebuild each benchmark repository once before evaluating cases.
- Tightened role detection so packages such as `src/_pytest` are not classified as tests just because their name contains `pytest`.
- Further reduced non-requested test and playground/example ranking noise after Vue monorepo testing.

## 0.8.5

- Reduced non-requested documentation, examples and playground ranking noise in context packs after harder Vite dependency optimizer testing.
- Added a regression test for operational queries where source files should beat matching docs/playground files unless the query explicitly asks for docs or examples.

## 0.8.4

- Added harder lab cases for Express static file sending, Django migrations and Vite dependency optimizer cache.

## 0.8.3

- Added `experiments/evaluate.py --strict` with configurable top-3/top-5/noise thresholds.
- Added summary hit rates to experiment evaluation output.

## 0.8.2

- Extract Python functions and methods with multiline signatures.
- Added harder validation cases for Django CSRF, Flask request hooks and Requests redirects/cookies.

## 0.8.1

- Added Requests and Vite cases to the local experiments harness.
- Excluded `.ai` design files by default after testing on Requests.

## 0.8.0

- Added a local `experiments/` validation harness with repeatable real-repo cases.
- Added expected useful files and noise patterns for Django, Express, Flask, Fastify, Gin and mini-redis.
- Added `experiments/evaluate.py` to report top-1/top-3/top-5 hits, noise hits and elapsed time.

## 0.7.1

- Excluded `.github` by default after testing on Gin, where workflow files added non-code ranking noise.

## 0.7.0

- Added basic Go language detection and regex symbol/import extraction.
- Added basic Rust language detection and regex symbol/import extraction.
- Included `.go` and `.rs` source files in source-file context scoring preferences.

## 0.6.3

- Excluded `.svg` files by default after testing on Flask, where documentation icons added noise to context results.

## 0.6.2

- Expanded the shared function-word filter after testing on the Express JavaScript repository.
- Prevented query words such as `and`, `where` and `with` from becoming symbol/path scoring signals.

## 0.6.1

- Added a small shared function-word filter for natural-language queries and local term statistics.
- Prevented words such as `why`, `are`, `not`, `after`, `perche`, `dove` and similar grammar terms from becoming code-ranking signals.
- Made soft path/filename matching more selective to avoid noisy matches such as incidental short prefixes.
- Increased test-file deprioritization for non-test-aware operational queries.

## 0.6.0

- Added metadata-only local term statistics in SQLite through the `term_stats` table.
- Rebuilt term statistics after `map`, changed-file `refresh`, and Git imports.
- Context scoring now prefers repository-adaptive token weights when available, with fallback for older databases.
- Reduced reliance on fixed scoring assumptions by letting each repository downweight its own common vocabulary.

## 0.5.6

- Optimized context relation scoring on large repositories by indexing candidate path suffixes instead of scanning candidates for every relation.
- Improved first-run usability on large codebases.

## 0.5.5

- Reduced context ranking noise from generic natural-language query terms such as `file`, `repo`, `repository` and `project`.
- Kept the filter generic rather than adding domain-specific synonyms.

## 0.5.4

- Hardened context token matching for natural-language queries.
- Ignored very short non-technical tokens such as incidental function words.
- Made path and filename matches boundary-aware so tiny substrings no longer create noisy candidates.

## 0.5.3

- Added conservative soft lexical matching for path and filename tokens.
- Improved matches such as `installazione` to `install` and `sessione` to `session` without hardcoded domain synonyms.

## 0.5.2

- Added `init-agent estimate <query>` to estimate context-pack token savings.
- Added JSON output for token estimates.
- Kept token estimation local with a simple `ceil(characters / 4)` heuristic.

## 0.5.1

- Limited `recent_commits[*].files` output to 10 files per commit.
- Added `total_files` and `files_truncated` fields to commit output.
- Made Markdown commit output compact for large commits.

## 0.5.0

- Added `init-agent run <query>` mini-harness.
- Automatically initializes, maps or refreshes, imports Git metadata when available, and generates a context pack.
- Added JSON and Markdown output for `run`.

## 0.4.x

- Added incremental `refresh`.
- Added `doctor` diagnostics.
- Improved context scoring for rarity, source/test balance, role/type weighting and noisy file ignores.
- Added configurable ignore rules in `.agent/config.json`.

## 0.3.x

- Added `doctor` readiness checks.

## 0.2.x

- Added `context` packs for AI coding agents.

## 0.1.x

- Initial project mapping, SQLite graph store, Git import, status, query and related-file lookup.
