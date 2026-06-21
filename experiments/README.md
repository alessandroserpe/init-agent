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
python3 experiments/evaluate.py --case django-auth-session-middleware
python3 experiments/evaluate.py --strict
python3 experiments/evaluate.py --strict --rebuild-index
python3 experiments/evaluate.py --case django-auth-session-middleware --measure-manual-scan
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
- `/tmp/init-agent-bench-init-agent`
- `/tmp/init-agent-bench-laravel-framework`

Missing repositories are skipped.

Suggested setup for public benchmark repositories:

```bash
git clone https://github.com/django/django.git /tmp/init-agent-bench-django
git clone https://github.com/expressjs/express.git /tmp/init-agent-bench-express
git clone https://github.com/pallets/flask.git /tmp/init-agent-bench-flask
git clone https://github.com/fastify/fastify.git /tmp/init-agent-bench-fastify
git clone https://github.com/gin-gonic/gin.git /tmp/init-agent-bench-gin
git clone https://github.com/tokio-rs/mini-redis.git /tmp/init-agent-bench-mini-redis
git clone https://github.com/psf/requests.git /tmp/init-agent-bench-requests
git clone https://github.com/vitejs/vite.git /tmp/init-agent-bench-vite
git clone https://github.com/pytest-dev/pytest.git /tmp/init-agent-bench-pytest
git clone https://github.com/vuejs/core.git /tmp/init-agent-bench-vue-core
git clone https://github.com/YOUR_USERNAME/init-agent.git /tmp/init-agent-bench-init-agent
git clone https://github.com/laravel/framework.git /tmp/init-agent-bench-laravel-framework
```

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
- `candidate_file_count`
- `manual_scan_file_count`
- `manual_scan_reduction_percent`

Use `--case <name>` to isolate one benchmark while tuning a ranking issue. The
flag can be passed more than once.

Use `--measure-manual-scan` when you want an explicit local IO comparison. It
reads all indexed files for each case repository and adds:

- `manual_scan_elapsed_seconds`
- `manual_scan_characters`

This is not a human-time estimate. It is a reproducible baseline for "how long
does a broad local read take compared with generating the context pack?"

The manifest intentionally includes both normal operational queries and
counter-cases where documentation, examples, tests, CSS or migrations should be
allowed to rank highly. This helps catch overfitting from one benchmark fix.
Cases with `"command": "overview"` use `init-agent run --overview --json` and
measure broad repository orientation instead of task-specific context ranking.

Cases may include `notes` for known weak areas. For example, Vue compiler
transform queries currently have overlapping compiler/runtime terminology that
can surface nearby relevant files before the exact expected transform files.

`--strict` exits non-zero if the summary misses the configured thresholds.
Defaults are:

- top-3 hit rate >= 0.85
- top-5 hit rate >= 1.0
- total noise hits <= 2

This is intentionally small and local. It does not call an LLM and does not
send repository contents anywhere.
