# Django Hidden-Cause Comparison

This experiment compares two fresh agent runs on a large Django checkout:

- a baseline agent that was not allowed to use `init-agent`
- an agent required to start with `init-agent`

Both agents received the same high-level regression task. The prompt did not
name the target function, file or module. The failing test lived in
`tests/template_tests/test_response.py`, while the underlying source fix was in
`django/utils/html.py`.

This is an observed run, not a scientific benchmark. It is included to show the
shape of a real agent workflow on a large repository where the symptom is not a
direct string search for the implementation file.

## Result

| Metric | Baseline | With init-agent |
| --- | ---: | ---: |
| Repository size | 7,018 files | 7,018 files |
| Outcome | PASS | PASS |
| Targeted tests | 1 OK | 1 OK |
| Approx wall-clock | ~8 min | ~1.5 min |
| Files read | 7 | 6 |
| Correct source file read position | 3rd | 3rd |
| Files modified | 2 | 2 |
| Logged commands | 22 | 11 plus init-agent |
| init-agent commands | 0 | 5 |

## Interpretation

The init-agent run did not skip verification or magically jump straight to the
fix. It still inspected files, hit one noisy initial match, and had to resolve a
secondary HTTPS warning in the high-level test.

The useful signal was reduced orientation/search churn:

- the baseline used broader text search and more exploratory commands
- the init-agent run used orientation plus targeted follow-ups
- both reached the correct source file as the third file read
- both produced a minimal source fix and passed the same targeted test

This supports a narrow claim: on large repositories with indirect symptoms,
`init-agent` can help an agent converge faster on the relevant area. It does
not replace `rg`, tests or direct source verification.

## Files

- `task.md`: shared task given to both agents
- `prompts/baseline_no_init_agent.md`: baseline run rules
- `prompts/with_init_agent.md`: init-agent run rules
- `logs/baseline_agent_log.md`: baseline run log
- `logs/init_agent_log.md`: init-agent run log
- `patches/final_fix.diff`: final source/test diff produced by both agents
- `results.md`: human-readable report
- `results.json`: machine-readable summary

The Django checkout, copied worktrees, `.agent/` index and virtualenv are not
committed.
