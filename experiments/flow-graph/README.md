# Flow Graph Diagnostic Experiment

This experiment checks whether the current init-agent graph contains the
runtime-flow edges an agent would need before ranking or embeddings are added.

It is intentionally not an agent benchmark. It asks a lower-level question:

> Given a small framework-shaped project, does the SQLite graph contain the
> route/include/import/call edges needed to follow the execution path?

## Run

From the repository root:

```bash
python3 experiments/flow-graph/evaluate.py
```

The script builds temporary fixture repositories, runs the current scanner and
writes:

- `experiments/flow-graph/results/results.json`
- `experiments/flow-graph/results/results.md`

## Cases

- `php_legacy_flow`: procedural PHP with bootstrap, includes, DB helper and
  render functions.
- `fastapi_flow`: FastAPI-style route, service, repository and model files.
- `django_flow`: Django-style URL config, view, model and template.
- `react_flow`: React/Vite-style main file, app component, child component and
  API client.

## How To Read It

`present` expectations are edges that should be visible in the graph today.
`limitation` expectations document runtime-flow facts that are intentionally or
currently not represented, such as SQL table usage, template rendering targets
or unresolved relative imports.

If a `present` expectation fails, the graph is missing a basic edge. If many
`limitation` expectations are important for real tasks, init-agent needs a more
semantic flow extractor before ranking can reliably improve.

