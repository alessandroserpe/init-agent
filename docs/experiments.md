# Validation Experiments

The `experiments/` directory contains a small local evaluation harness. It
compares context-pack candidates against expected useful files for real
repositories and counter-cases.

The benchmark exists to catch obvious regressions when scoring or extraction
changes.

The directory also contains a small number of observed agent comparisons. Those
are not scientific benchmarks; they are lightweight evidence about how
`init-agent` changes an agent's search path on real repositories.

## Run

```bash
python3 experiments/evaluate.py
python3 experiments/evaluate.py --case django-auth-session-middleware
python3 experiments/evaluate.py --strict
python3 experiments/evaluate.py --strict --rebuild-index
python3 experiments/evaluate.py --case django-auth-session-middleware --measure-manual-scan
```

## What It Reports

- top-1/top-3/top-5 hits
- obvious noise matches
- elapsed time
- compact candidate count
- indexed file count avoided by broad scan reduction

Missing optional benchmark repositories under `/tmp` are skipped.

Use `--case <name>` to isolate one query and `--rebuild-index` after changing
scanner, symbol extraction, role detection or scoring code.

## Current Coverage

The manifest includes cases for projects such as Django, Express, Flask,
Fastify, Gin, mini-redis, Requests, Vite, pytest and Vue Core. It also includes
counter-cases where docs, examples, CSS or tests are intentionally relevant.

That mix is deliberate: scoring changes should reduce noise without breaking
recall for cases where a usually-noisy file type is actually the right answer.

## Real-World Agent Comparison

`experiments/django-hidden-cause/` records an observed hidden-cause regression
test on Django, a checkout with 7,018 files.

Two fresh agents received the same task:

- `baseline_no_init_agent`: normal repository exploration, no init-agent
- `with_init_agent`: required to start with init-agent orientation

Both agents passed the targeted test. In this run, the init-agent-assisted agent
used fewer exploratory commands and less estimated wall-clock time:

| Metric | Baseline | With init-agent |
| --- | ---: | ---: |
| Approx wall-clock | ~8 min | ~1.5 min |
| Files read | 7 | 6 |
| Logged commands | 22 | 11 plus init-agent |
| Targeted test | PASS | PASS |

The task did not name the implementation file or function. The failing test was
high-level template response behavior; the source fix was in
`django/utils/html.py`.

This experiment should be read as an observed workflow comparison, not as a
general benchmark claim. It shows where init-agent is most useful: large
repositories, indirect symptoms and expensive orientation.
