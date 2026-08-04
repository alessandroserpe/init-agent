# init-agent Experiments

This directory contains repeatable orientation benchmarks and archived paired
agent observations. They measure whether useful files appear early and how much
noise remains; they do not prove that an agent will solve a task faster or
produce a better patch.

The complete methodology, metrics, setup instructions and interpretation limits
are documented in [../docs/experiments.md](../docs/experiments.md).

## Deterministic Orientation Benchmark

Run the local deterministic cases:

```bash
python3 experiments/evaluate.py
python3 experiments/evaluate.py --strict --min-cases 4
```

External benchmark repositories under `/tmp/init-agent-bench-*` are optional
and skipped when absent. Rebuild their indexes after extractor or scoring
changes:

```bash
python3 experiments/evaluate.py --strict --min-cases 4 --rebuild-index
```

Write JSON, CSV and Markdown artifacts with:

```bash
python3 experiments/evaluate.py --strict --min-cases 4 --output-dir experiments/results
```

Charts require optional `matplotlib`:

```bash
python3 experiments/plot_results.py experiments/results/results.csv
```

## Graph Resolution Diagnostic

The flow-graph fixture suite checks whether supported imports, includes, calls,
routes and templates resolve to real files without broad ambiguous edges:

```bash
python3 experiments/flow-graph/evaluate.py --strict --min-resolution-rate 1.0
```

## Agent Runs

`django-hidden-cause/` preserves one observed paired run with prompts, logs,
patches and limitations. `agent-runs/` documents the layout for future A/B
runs. These artifacts are workflow evidence, not a scientific performance
claim.
