# Enclosing-symbol context: isolated experiment

2026-10-16. Reproduce: `python3 -m experiments.search_symbol_context`.
Raw results: `experiments/search-symbol-context/results.json`.

The experiment updates names in temporary FTS indexes only. Production/prototype
indexing and ranking code are unchanged. No model or dependency is involved.

## Hypothesis and method

The current 24-line windows carry a symbol name only when its declaration starts
inside the window. The alternative also carries names of symbols whose known
line/end_line interval contains the first line of the window. Unknown ends are
not extrapolated. Compare the same source, query and ranking before/after.

Four synthetic long functions use different names and error details, with and
without a short guide mentioning the same terms: eight cases total. These are
variants of one mechanism, not independent real-world validation. The intended
evidence is the implementation's error statement; the guide can also be useful
and is not universally an incorrect search result.

## Observed results

- Without the guide, the top result includes the intended implementation passage
  in 0/4 baseline cases and 4/4 experimental cases. The file was already found;
  the improvement is which passage is returned.
- In all eight cases, the implementation hit gains the all_terms channel.
- With the guide, it remains first in all four cases: no file-order improvement.
  The current proximity rule favors literal co-occurrence in the excerpt; the
  added enclosing name lives in metadata, outside that excerpt.
- A window covering the end of outerScope and the next unrelated function
  falsely combines outerScope metadata with foreignneedle from the next
  function. Interval overlap is insufficient to assert common symbol ownership.
- Clearing end_line does not extend the enclosing name into later windows.
- For a nested function, child context matches its inner evidence and does not
  reach distant outer-function evidence; the parent matches its own later body.
  This does not resolve windows crossing nested boundaries.

All 61 existing focused tests pass after the experiment. This verifies isolation
and preserves current regressions; it does not validate the experimental index
as ready for integration. Log: /tmp/init-agent-symbol-context-tests.log.

## Decision

Keep the experiment, do not integrate unconditional name propagation. Symbol
context is useful for passage selection, but fixed windows crossing scope
boundaries can create false associations. Next evaluate passages split at known
symbol boundaries, with explicit enclosing context and conservative fallback
where end_line is absent. Include adjacent/nested scope negative controls,
real-repository evidence, index size and update cost. Reconsider proximity only
in a separate comparison, so structural context and ranking effects are not
confounded. An integrated index change needs versioned rebuilds even when file
hashes stay unchanged.
