# init-agent Experiments

This folder is for validating whether `init-agent` is useful on real tasks.

The goal is not to prove that every ranking is perfect. The goal is to collect
repeatable cases where we can compare:

- the query
- the files `init-agent` suggests first
- the files we expected to be useful
- obvious noise
- rough timing

Run the evaluator from the project root:

```bash
python3 experiments/evaluate.py
python3 experiments/evaluate.py --strict
python3 experiments/evaluate.py --strict --rebuild-index
```

By default it expects local benchmark repositories under `/tmp`, for example:

- `/tmp/init-agent-bench-django`
- `/tmp/init-agent-bench-express`
- `/tmp/init-agent-bench-flask`
- `/tmp/init-agent-bench-fastify`
- `/tmp/init-agent-bench-gin`
- `/tmp/init-agent-bench-mini-redis`
- `/tmp/init-agent-bench-requests`
- `/tmp/init-agent-bench-vite`
- `/tmp/init-agent-bench-pytest`
- `/tmp/init-agent-bench-vue-core`

Missing repositories are skipped.

Use `--rebuild-index` after changing scanner, role detection, symbol extraction
or scoring code. It runs `init`, `map` and `git` once per benchmark repository
before evaluating cases, so results are not based on stale `.agent/` indexes.

Each case reports:

- `top1_hit`
- `top3_hit`
- `top5_hit`
- `expected_hits`
- `noise_hits`
- `elapsed_seconds`

The manifest intentionally includes both normal operational queries and
counter-cases where documentation, examples, tests, CSS or migrations should be
allowed to rank highly. This helps catch overfitting from one benchmark fix.

`--strict` exits non-zero if the summary misses the configured thresholds.
Defaults are:

- top-3 hit rate >= 0.85
- top-5 hit rate >= 1.0
- total noise hits <= 2

This is intentionally small and local. It does not call an LLM and does not
send repository contents anywhere.
