# Validation Experiments

The `experiments/` directory contains a deterministic repository-orientation
benchmark. It compares context-pack candidates against expected useful files for
real repositories and counter-cases.

The benchmark exists to catch obvious regressions when scoring or extraction
changes. It does not measure whether an agent solves a task end-to-end.

The directory also contains a small number of observed agent comparisons. Those
are not scientific benchmarks; they are lightweight evidence about how
`init-agent` changes an agent's search path on real repositories.

## What The Benchmark Measures

The deterministic benchmark measures whether `init-agent` points an agent toward
useful files early in the generated context pack.

Primary metrics:

- `top1_hit`: the first suggested file is one of the expected useful files
- `top3_hit`: at least one expected useful file appears in the first 3 results
- `top5_hit`: at least one expected useful file appears in the first 5 results
- `noise_hits`: candidate files matching case-specific known-noise patterns
- `candidate_file_count`: number of files suggested by the context pack
- `elapsed_seconds`: time to generate the context pack
- `manual_scan_reduction_percent`: indexed file-count reduction from broad scan
  to candidate set
- `expected_file_ranks`: 1-based positions for each expected file
- `missing_expected_files`: expected files absent from the candidate set

The benchmark intentionally makes a narrow claim:

> In deterministic repository-orientation benchmarks, init-agent measures
> whether expected useful files appear early in the generated context pack.

## What It Does Not Measure

This benchmark does not measure:

- whether a coding agent fixed a bug
- final patch quality
- reasoning quality
- user satisfaction
- exact token billing
- end-to-end wall-clock time in an interactive agent session

Observed paired agent runs, such as the Django hidden-cause comparison below,
can provide additional workflow evidence. They should still be treated as
observed runs, not broad performance claims.

## Run

```bash
python3 experiments/evaluate.py
python3 experiments/evaluate.py --case django-auth-session-middleware
python3 experiments/evaluate.py --strict
python3 experiments/evaluate.py --strict --rebuild-index
python3 experiments/evaluate.py --case django-auth-session-middleware --measure-manual-scan
python3 experiments/evaluate.py --strict --output-dir experiments/results
```

## What It Reports

By default, `evaluate.py` prints a JSON report to stdout.

Use `--output-dir` to write all standard artifacts:

```bash
python3 experiments/evaluate.py --strict --output-dir experiments/results
```

This writes:

- `experiments/results/results.json`
- `experiments/results/results.csv`
- `experiments/results/summary.md`

You can also choose individual output paths:

```bash
python3 experiments/evaluate.py \
  --json-output /tmp/init-agent-results.json \
  --csv-output /tmp/init-agent-results.csv \
  --markdown-output /tmp/init-agent-summary.md
```

Missing optional benchmark repositories under `/tmp` are skipped.

Use `--case <name>` to isolate one query and `--rebuild-index` after changing
scanner, symbol extraction, role detection or scoring code.

## Charts

Generate simple PNG charts from a CSV report:

```bash
python3 experiments/plot_results.py experiments/results/results.csv
```

The chart script writes:

- `hit_rates.png`
- `noise_hits.png`
- `elapsed_seconds.png`
- `manual_scan_reduction.png`

`matplotlib` is intentionally optional. If it is missing, the script exits with
a clear install message:

```bash
python3 -m pip install matplotlib
```

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
used fewer exploratory commands and less estimated wall-clock time in the agent
logs:

| Metric | Baseline | With init-agent |
| --- | ---: | ---: |
| Approx logged wall-clock | ~8 min | ~1.5 min |
| Logged files read | 7 | 6 |
| Logged commands | 22 | 11 plus 5 init-agent commands |
| Targeted test | PASS | PASS |

The task did not name the implementation file or function. The failing test was
high-level template response behavior; the source fix was in
`django/utils/html.py`.

This experiment should be read as an observed workflow comparison, not as a
general benchmark claim. It shows where init-agent is most useful: large
repositories, indirect symptoms and expensive orientation.

## Future Agentic A/B Runs

Future paired agent runs should live under `experiments/agent-runs/` with a
repeatable structure:

```text
experiments/agent-runs/
  <case-name>/
    baseline_run_01/
      prompt.md
      transcript.txt
      metrics.json
    init_agent_run_01/
      prompt.md
      transcript.txt
      metrics.json
```

Those runs can measure agent behavior such as files read, commands run,
time-to-first-relevant-file, tests run and final patch quality. They are a
different layer from the deterministic orientation benchmark in
`experiments/evaluate.py`.
