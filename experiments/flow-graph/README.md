# Flow Graph Diagnostic Experiment

This experiment checks whether the current init-agent graph extracts runtime
relations and persists unambiguous targets as concrete `resolved_file` and
`resolved_symbol` edges.

It is intentionally not an agent benchmark. It asks a lower-level question:

> Given a small framework-shaped project, does the SQLite graph contain the
> route/include/import/call/inheritance edges needed to follow the execution
> path and attribute calls to concrete functions or methods?

## Run

From the repository root:

```bash
python3 experiments/flow-graph/evaluate.py
python3 experiments/flow-graph/evaluate.py --strict --min-resolution-rate 1.0
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
- `python_inheritance_flow`: imported Python base class and scoped method call.
- `php_inheritance_flow`: PHP inheritance and scoped call inside an include
  component.
- `scoped_call_ranking`: imported calls competing with unrelated duplicate
  definitions.
- `hidden_test_symbol_ranking`: a symptom query that matches a test method and
  should promote the production function reached by its resolved call.
- `ambiguous_symbol_guard`: an unscoped duplicate name that must remain
  unresolved.

## How To Read It

`present` expectations report extraction and resolution separately. A target
expectation passes only when SQLite contains the concrete `resolved_file`
edge; the evaluator no longer resolves the target on behalf of the graph.
`absent` expectations are precision guards: ambiguous names must not create
file edges.

Ranking diagnostics compare the same fixture with and without resolved edges.
They report Top-3 coverage, rank regressions and scoped noise reduction. This
is a deterministic graph/ranking diagnostic, not an agent-speed benchmark.
The bounded structural reranker starts from at most ten seeds, traverses one
resolved hop and penalizes broad fan-out. Query-matching test symbols may add
production files outside the first lexical candidates; ordinary queries keep
the direct lexical ranking as the dominant signal. Test-to-source promotion
requires a strongly matching leaf test name and a resolved behavioral edge;
generic test-class names and inheritance do not qualify.
