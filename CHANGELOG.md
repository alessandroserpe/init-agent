# Changelog

All notable changes to `init-agent` are documented here.

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
