# Bounded call-path evidence

2026-10-16. Experimental source implementation; no skill prompt, new dependency,
model, index migration or receiver-resolution changes.

`repo_search` with `include_relations=true` uses the enclosing callable of the strongest matching line in
its first lexical result as a seed. It follows existing resolved-symbol call
edges and returns `call_paths`, with at most one outgoing and one incoming path,
each at most two edges. Each edge includes caller/callee paths, qualified names,
indexed hashes, call-site line/text, a short target excerpt, resolver provenance
and confidence. This expands evidence to files absent from the lexical results;
it does not change the lexical ranking or the `limit` on those results.

Paths replace generic `graph_links` when available (those arrays become empty).
When no path is available, legacy file links remain. `call_path_diagnostics`
reports the seed, omitted branches, stale endpoints and the depth bound. New
fields are present for nonempty lexical results. No result is a claim that the
path is exhaustive, executed at runtime, or sufficient to solve the task.

## Compact default (2026-10-18)

Search now returns source evidence and freshness-checked memories without automatic
relations. `call_paths` and each hit's `graph_links` are empty by default; path
diagnostics are returned only for requested expansion. Use `include_relations=true`
in MCP/Python or `--include-relations` in `python -m init_agent.local_search` to
recover the expanded response. This is an intentional default-behavior change.

A hit inside a function or method returns that complete parser-bounded scope when
it fits within 1,400 characters, including across indexed passage boundaries.
`complete_symbol=true` distinguishes this from a window into a larger scope.
The source hash is verified before expansion. Large functions keep a bounded
window around the matching line; unknown scope ends are never invented.
Memory freshness warnings and retrieval ranking are unchanged.

## Selection and bounds

Only callable symbols enclosing the actual evidence line can seed traversal.
Imports and adjacent functions cannot stand in for a callable. Incoming and
outgoing directions stay separate: the search cannot jump from a caller to an
unrelated sibling callee. A branch is followed when it is unique, or one neighbor
has uniquely greater symbol-name overlap with the question. Confidence of an
edge is not used to break a relevance tie. Ambiguous branches stop traversal and
are reported. Nodes with more than 12 neighbors in that direction are not
expanded. Cycles are suppressed within each path.

Every endpoint must be present in the full-text source inventory, satisfy source
path restrictions and exclusions, and still match its indexed content hash.
Unresolved calls, missing line evidence, stale/deleted endpoints and unindexed
sources are not returned. Original call-site direction is retained even while
traversing incoming edges. This does not resolve the previously identified
nonlocal `worker.tick()` call.

Returned call excerpts are at most 240 characters and target excerpts at most
400; clipping is flagged. Combined path JSON is capped at 5,000 characters by
removing farthest edges while preserving connection to the seed. Diagnostics
and lexical results are outside this path-only cap. Empty paths add a small
amount of diagnostic metadata. Candidate source reads are bounded by traversal
limits and the existing repository I/O/SQL/work budgets. No background work is
introduced, and no mandatory preparation or feedback call is added.

## Verification

Eight new tests cover nonlexical two-hop evidence, reverse callers, same-name
decoys, unknown receivers, stale/deleted/filtered endpoints, cycles, hubs,
missing call-line metadata, ambiguous versus explicitly named branches,
import-only matches, source-index exclusion, MCP propagation and budget clipping
that preserves seed connectivity. The existing source-evidence assertion was
updated to check actual caller paths instead of generic file links.

The full working-tree suite ran 408 tests with two skips and one sandbox-only
socket error. That sole test passed on a separate run with temporary Unix socket
permission. Two additional path tests were then added; all eight dedicated tests
passed. No LLM benchmark was run. Logs are in /tmp/init-agent-path-*.log.

## Same-index diagnostic comparison

`python3 -m experiments.search_call_paths` initializes one disposable source-only
copy and alternates lexical-only and path-enabled calls, six calls per mode/query.
The baseline bypasses only call-path extraction; it retains the original file
links. Both modes use the same source index. These are three selected diagnostic
queries, not a held-out or cross-repository benchmark. They exclude tests/docs
and user memories. Character counts are JSON characters, not model tokens.

| Query | Lexical chars | With paths | Median local time, lexical -> paths |
| --- | ---: | ---: | ---: |
| Maintainer.tick | 5,117 | 5,317 | 10.84 -> 11.44 ms |
| fingerprint iter_project_files | 3,971 | 5,026 | 10.47 -> 11.08 ms |
| Git inventory fallback gitignore | 4,454 | 4,628 | 6.97 -> 7.94 ms |

The fingerprint query adds `init_agent/utils.py`, absent from the lexical top
three, through `fingerprint -> iter_project_files -> iter_indexable_files`.
The Git query shows `iter_indexable_files -> _git_indexable_paths -> run_git_read`.
The Maintainer query abstains on ambiguous branches. An early prototype chose an
arbitrary caller branch for the Git query; this was observed and removed before
these measurements. Do not count that abandoned branch as a useful result.

Raw outputs: `experiments/graph-audit/retrieval-comparison.json`.
The earlier extraction audit can also be reproduced; its path-enabled output is
`experiments/graph-audit/with-call-paths.json`.

## Remaining work

The first lexical hit remains a bottleneck. An irrelevant seed or an ambiguous
branch can produce no useful path. Two-hop depth, name overlap and direction
bounds intentionally sacrifice coverage. This prototype demonstrates delivery
of additional verified structural evidence; it does not demonstrate lower total
agent tokens or faster task completion. Local constructor/parameter type
resolution remains a separate next change, with conservative negative cases.

## Compact response check, 2026-10-18

Compared the current response with `HEAD`'s previous search implementation on the
same existing local index, restricted to `init_agent/` with `limit=1`. This is a
known-case output comparison, not a blind agent benchmark or measured time saving.
The first file stayed unchanged for all three queries.

| Query | Previous JSON characters | Compact JSON characters | Compact scope |
| --- | ---: | ---: | --- |
| saved note stale file changed deleted hash | 5,431 | 4,143 | memory.py:444–472, complete |
| with_live_staleness | 4,724 | 3,609 | memory.py:437–441, complete |
| search_terms | 5,711 | 4,247 | search_tokens.py:8–26, complete |

Sizes use `len(json.dumps(response))`, not model tokens. The first query previously
returned lines 450–461 plus a deletion-related incoming path; the compact response
contains the complete decision and leaves relationship expansion to the caller.
Regression tests also cover three distinct decision vocabularies across passage
boundaries, large functions, nested scopes, long preceding lines, and MCP opt-in.
