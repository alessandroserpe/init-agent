# Validation Experiments

The `experiments/` directory contains a small local evaluation harness. It
compares context-pack candidates against expected useful files for real
repositories and counter-cases.

The benchmark exists to catch obvious regressions when scoring or extraction
changes.

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
