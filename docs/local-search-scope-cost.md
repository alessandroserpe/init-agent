# Measured cost of scope-bounded passages

2026-10-16. Reproduce with `python3 -m experiments.search_scope_cost`.
Raw observations: `experiments/search-symbol-context/cost-results.json`.

## Protocol

Export commit 14636ac00129565d298811bd0e61a7024c88e800 once and prepare its graph.
Copy this seed into independent temporary repositories. Run three fresh Python
processes per variant, alternating variant order between rounds. Both variants
use the same read/SQL insertion/commit pipeline; only passage generation changes.
This prevents comparing production hash/freshness work with a stripped-down
experimental rebuild. No production index is mutated.

Each process measures one full search-chunk rebuild and five reindexes of the
largest indexed Python file, then compacts SQLite identically outside timing.
Search uses ten fixed queries (broad, identifier, path, Italian request and
no-result control), one warm-up per query and seven timed repetitions. This
produces 210 timed searches per variant. Each timed search opens its own database
connection; the OS cache remains warm. Peak RSS is the fresh process high-water
mark across all phases, not isolated search RAM. No model calls or installs.

## Observations on this Mac

| Measurement | Fixed windows | Scope boundaries |
| --- | ---: | ---: |
| Full chunk rebuild, median | 186.8 ms | 241.8 ms |
| One-file chunk reindex, median | 10.7 ms | 12.0 ms |
| Warm query latency, pooled median | 16.0 ms | 13.1 ms |
| Warm query latency, pooled p95 | 34.0 ms | 43.8 ms |
| Exact symbol query, median | 17.7 ms | 21.1 ms |
| Exact path query, median | 33.8 ms | 43.8 ms |
| Compacted entire database | 11,243,520 bytes | 11,374,592 bytes |
| Search tables via dbstat | 5,246,976 bytes | 5,378,048 bytes |
| Median process peak RSS | 45.7 MiB | 45.7 MiB |
| Chunk count | 1,897 | 4,325 |

The database grows by 131,072 bytes (128 KiB); search tables grow about 2.5%.
Full rebuilding adds about 55 ms (+29%) here. Single-file timing concerns search
rows only: it does not include a source edit, graph refresh or full watcher
cycle. Full rebuilding likewise excludes graph initialization. It is not a
measurement of full init-agent startup.

Most broad queries are quicker in these runs, but exact symbol/path queries
are slower. An absent-term query also slows (7.6 to 13.1 ms median); its cause
is not established. Do not describe the new search as uniformly faster. The
raw runs include timing outliers (including a baseline query at 343 ms), and
only three processes per variant were measured. This is a small local comparison,
not a statistically established performance guarantee.

Returned JSON averages roughly 4.3 KB versus 3.9 KB over these ten queries.
Different passages/results are returned: byte reduction is not proof of equal
answer quality, token savings or fewer agent calls. It is serialized JSON size,
not model-token accounting.

## Decision and limits

The extra chunk count is not itself a resource blocker on this repository:
measured disk and process-memory overhead are small, and rebuild overhead is
milliseconds. The latency tradeoff for exact lookup is real in this sample and
should be preserved as a regression measurement rather than hidden by a pooled
median. These observations do not establish behavior on large repositories,
low-memory machines, cold caches or other operating systems.

Combined with the earlier passage-evidence and boundary checks, this supports
continuing toward an experimental integration; cost alone does not justify
discarding it. Before switching live indexing, implement versioned transactional
rebuilds and verify incremental maintenance. It remains a passage-quality change,
not a demonstrated fix for generic semantic ranking. No integration occurred
in this cost measurement.
