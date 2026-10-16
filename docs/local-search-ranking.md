# General retrieval signals — experimental revision

No repository-specific words, paths, expected answers or role bonuses were added.
The revision combines bounded candidate channels:

1. Exact symbol/qualified-name or repository-path lookup for a single-item query.
   Definitions are distinguished from documentation headings and command examples.
2. Full-text matches containing all query terms (including FTS stemming).
3. Partial full-text matches as fallback.

Within these tiers, literal term proximity and BM25 order results. Duplicate
chunks are merged before selecting one result per file. Each channel retrieves
at most 80 rows; cap indicators and retrieval reasons are returned. Source
freshness, SQL note retrieval, file exclusions and output caps remain enforced.
No general preference for implementation over documentation or tests is imposed.
Graph links are still supplied as supporting evidence; no new graph expansion
or natural-language interpretation is claimed.

## Frozen checks

Before implementation, twelve small synthetic cases were written in
`tests/fixtures/local_search_cases.json`. Six were used for development; six
were first executed after the implementation adjustment. Both sets were designed
by the same author, so this is a development/validation separation, not blind
independent evaluation. Cases cover symbols, explicit paths, multi-term search,
error text, body-only evidence, no-match, documentation, configuration, morphology
and tests. They do not establish cross-repository performance.

| Set | Previous top-1 correct | Revised top-1 correct |
| --- | ---: | ---: |
| Development | 4/6 | 6/6 |
| Validation | 4/6 | 6/6 |

The improvements are exact-symbol and exact-path lookups in both sets. Other
cases are unchanged: there is no measured gain attributable to proximity or
all-term retrieval in this small corpus. They should not be credited with the
four improvements. No changed result regressed in these fixtures.

The original ranker is preserved in `experiments/search-ranking/baseline.py` as
an experimental artifact, not another production implementation. Fixture and
baseline hashes and per-case outcomes are in `experiments/search-ranking/results.json`.
Reproduce with `python3 -m experiments.search_ranking development` or `validation`.
The fixture expectations also run in `tests.test_local_search`.

## Existing repository queries

The same four broad historical keyword queries were rerun on the same exported
revision `14636ac`. Their top-three file ordering is unchanged, both unscoped
and code-scoped. The two previously missing reference implementations remain
missing from the code-scoped top three. These broad-query limitations are not
fixed by exact-name retrieval.

The new run took roughly 12–14 ms per query versus the earlier 4.8–5.4 ms; these
are single local observations, not controlled latency measurements. JSON grows
by roughly 149–162 bytes per response because retrieval diagnostics were added.
Thus the revision adds local work and a small output cost; no model token or
end-to-end time saving has been measured. Full results are in
`experiments/search-ranking/replay-after.json`; the earlier replay remains in
`docs/local-search-replay.json`.

58 focused tests pass. No model calls, benchmark restart, merge or production
installation occurred. Exact-target retrieval is more reliable in these checks;
broad behavioral queries still require stronger evidence or a more specific
query. Further work should use new cases and inspect missing candidates versus
ordering errors separately, without inserting special rules for these examples.
