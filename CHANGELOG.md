# Changelog

All notable changes to `init-agent` are documented here.

## 0.9.2

- Added internal index versioning so `run` rebuilds stale indexes after extractor changes instead of trusting unchanged file hashes.
- `refresh` and `doctor` now report stale indexes clearly and suggest `init-agent map`.
- `run`, `context`, `query` and `estimate` now accept unquoted multi-word queries.

## 0.9.1

- Expanded PHP builtin exclusions so common runtime/helper calls do not dominate call graph output.
- Added `init-agent callers <symbol>` to show definitions and files that call a function or symbol name.
- Added `init-agent symbol <symbol>` to show definitions, callers, candidate files and recent commits for a symbol.
- Aggregated caller output with call counts and first call line per file.
- Added optional fc5 benchmark cases for PHP procedural calls, discussion badge flow and CRUD builder orientation.

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
