# Scope-bounded passage experiment

2026-10-16. Run `python3 -m experiments.search_scope_chunks`.
Results: `experiments/search-symbol-context/scope-results.json`.

## Implementation scope

Implemented an experimental passage generator and temporary-index comparison.
The production/prototype search and maintenance implementation is unchanged.
No models, packages, startup prompt additions or network calls are required.

Known symbol intervals create boundaries at declaration and end+1. Within each
constant-scope interval, windows retain the existing 24-line size and 20-line
stride. The active enclosing names are indexed as metadata. Nested intervals
use a counter, so a child with the same name does not remove its parent's name
when it ends. Missing or invalid end positions attach a name only to its
single declaration line. Files without symbols retain the original windows.
The experiment trusts parser line metadata; incorrect valid-looking intervals
cannot be detected by this algorithm. Parent membership does not imply that a
nested function's code executes directly as part of the parent.

## Results

| Check | Baseline | Scope-bounded |
| --- | ---: | ---: |
| Implementation excerpt contains intended evidence, eight synthetic variants | 0/8 | 8/8 |
| Existing ranking/crowding/no-answer fixture checks | 16/16 | 16/16 |
| False association across adjacent functions in the controlled case | Previous name-propagation experiment: 1 | 0 |
| False association of child name with distant outer evidence | 0 | 0 |

The eight examples vary four long-function names/details with/without a guide.
They test one mechanism, not eight independent generalization claims. The guide
remains first where present. Improvement is selection of the implementation
passage, not prioritizing implementation over documentation.

A temporary export of commit 14636ac00129565d298811bd0e61a7024c88e800 was also
indexed. Chunk count rises from 1,897 to 4,325 (+128%). Sum of UTF-8 text bytes
for excerpts/names/bodies falls from 3,146,216 to 2,993,320 (about -4.9%). These
are text payload sizes, not SQLite disk usage or process RAM. The increased
row count is a potential cost despite less repeated text. Rebuilding existing
search chunks on this small snapshot takes roughly 0.2 seconds in one local
run; this excludes initial mapping, is not an incremental-update measurement,
and is not a controlled timing comparison.

The four historical keyword queries change some positions but still do not
place the two weak reference files in the first three. These labels and keyword
bags retain the limitations documented in local-search-diagnosis.md. No agent
completion, token-saving or cross-repository quality claim follows.

65 focused tests pass, including four new generator tests for line coverage,
exact excerpt bounds, maximum passage length, adjacent/nested intervals,
duplicate names, missing/invalid ends, empty input and symbol-free fallback.
The separate comparison verifies all 16 existing retrieval fixtures under both
indexes. Log: /tmp/init-agent-scope-passages-tests.log.

## Decision

The mechanism is worth retaining as an experimental implementation: it improves
passage selection and resolves the demonstrated adjacent-scope contamination.
Do not silently replace the live index yet. Unknown-end declaration splitting
and many small scopes increase fragmentation; measure their contributions and
real-repository query cost before integration. Keep this separate from changing
ranking weights. An integrated version also requires an index version and
transactional rebuild on unchanged file hashes, plus incremental invalidation
checks. The current experiment rebuilds temporary indexes only.
