# Full-query retrieval correction

Date: 2026-10-16. Experimental worktree only; no model or dependency added.

## Reproduced issue

Search accepted requests up to 1000 characters but silently discarded all terms
beyond the first 16 distinct normalized terms. This affected source retrieval,
SQL note retrieval and selection of the displayed evidence. Important task
details at the end could not contribute to finding a result.

The new regression uses English and Italian request prefixes, source evidence
and a repository note. It moves the identifying terms from the beginning to the
end without changing the words. Before the fix, all four suffix cases lost the
expected result; the four prefix controls passed. A separate 1000-character
case also failed to retrieve its target (IndexError when checking the empty
results). Logs: /tmp/init-agent-full-query-before.log.

## Change and validation

Remove the 16-term slice. The existing 1000-character input bound still limits
query size; term deduplication, quoting, candidate caps, result limits and
freshness behavior remain in place. No repository-specific terms or ranking
weights were added. No index rebuild is required for this query-only change.

All 61 focused tests pass, including eight language/order/source-note cases,
the maximum-length request, frozen ranking and crowding cases, memory freshness,
maintenance, ignore refresh, relation resolution and index health. Log:
/tmp/init-agent-full-query-after.log.

This establishes correction of an input-loss bug, not general semantic search
quality or agent token savings. More terms may increase SQL work and noise;
real-repository long-request latency and ranking remain to be measured. The
returned terms list can also be larger. Existing output excerpt limits remain.

## Index observation for the next isolated experiment

The index uses 24-line windows with stride 20. Its names field includes a symbol
only when its declaration starts inside the window, although end_line metadata
is available. Later passages inside long functions lose that enclosing symbol
context. Test enclosing-symbol metadata or symbol-aware boundaries against the
current index, including false matches, nested definitions, incomplete end-line
metadata and long functions. This is an observation and proposed test, not an
implemented improvement or proven gain. Any index-format change will need an
explicit rebuild/version strategy even when source hashes are unchanged.
