# Broad-query diagnosis and candidate diversity

## Observed failure stages

On the exported `14636ac` snapshot, using the four existing keyword queries and
`init_agent/` scope, the reference files have unique-file ranks 1, 10, 12 and 1.
The two weak references are present among candidates: the first failure is not
absence from the index. No direct resolved-file edge connects their respective
top-three seeds to those references. Blind one-hop graph expansion therefore
has no demonstrated mechanism for rescuing them. The incoming/outgoing edge
inspection is retained in `experiments/search-diversity/diagnosis-before.json`.

These are retrospective reference labels, not the only useful answers. Some
references were created by the historical fixes; this is an audit of the later
snapshot, not historical first-file recall. The broad command keyword sets also
omit task details such as dashboard or imported alias. A relevant API wrapper
can be a valid first read even if it is not the eventual changed implementation.

## General issue reproduced

Every old query reached the lexical chunk cap. The engine previously selected
80 chunks and only then deduplicated files. A single long/repetitive document
could fill all 80, preventing other matching files from reaching the final list.

Four fixed synthetic repositories reproduce this with a long distractor and a
shorter relevant file: Python implementation, TypeScript configuration,
documentation, and a test. They were prepared before implementation. All baseline
outcomes were inspected, so the split labels are organizational only, not a blind
held-out validation claim or evidence across real external repositories.

## Change and outcome

Each lexical channel now selects at most two chunks per file **before** applying
its global 80-candidate limit, using a materialized FTS query and a per-file window
rank. No repository-specific terms, file-role bonuses or relevance weights change.
Exact-symbol/path lookup remains separate. Final output still caps at three
source files by default, with unchanged excerpt limits.

| Observation | Before | After |
| --- | ---: | ---: |
| Relevant file returned in four crowding fixtures | 0/4 | 4/4 |
| Relevant file ranked first in those fixtures | 0/4 | 0/4 |
| Original twelve synthetic top-1 checks | 12/12 | 12/12 |
| Top-three ordering in four broad historical queries | baseline | unchanged |

This improves candidate recall under repetition, not general semantic ranking.
Responses grow by about 393–436 bytes in the crowding fixtures because the
previously missing file now appears. The historical responses keep the same
size and ordering. Their single-run timings are about 12–27 ms; this is not a
controlled performance estimate. Materializing lexical matches can cost more
SQL work, and only two chunks per file can omit another useful passage. The
prototype requires SQLite with FTS5 and materialized CTE/window support, verified
on the interpreter used here.

59 focused tests pass, including the four crowding cases and prior freshness,
notes, scope, maintenance and exact-search checks. Reproduce the comparison with
`python3 -m experiments.search_diversity`. Baseline and raw outcomes are preserved
under `experiments/search-diversity/`.

No model calls or deployment occurred. The next unresolved issue is retrieval
for ambiguous behavioral requests. Before another ranking change, evaluate full
task context and evidence paths on new real repositories; do not label all nearby
results wrong simply because they differ from the reference patch file. This
iteration deliberately stops after one general, reproducible correction.
