# Optional task verification

When a task already has relevant files attached, execute a selected unittest
through the task instead of running it separately and manually recording its
result:

```sh
init-agent task verify 14 --test tests.test_task_checks --json
```

For this uninstalled working-tree version use `python3 -m init_agent.cli` in place
of `init-agent`. Task 14 and the selector above are examples from this repository.
The command executes repository code in the current Python environment; it does
not choose a test, discover missing dependencies, install packages or close tasks.
Only invoke it when intending to run that test. Default timeout is 60 seconds,
configurable up to 300 seconds with `--timeout`.

The task must exist and have linked files. These files plus the selected local
test module form the scope. One operation runs the test and persists its result
and file hashes in `.agent` metadata. There is no extra output file to manage.
The latest result per task/test replaces the previous result. A stable check id
identifies that task/test even when its file scope grows. This is not a run-history
store. Existing free-text remaining work is not inferred or automatically closed.

Normal task retrieval (`task list`, `repo_task_list`, Python `get_task`) and
session summary/close responses include up to five compact latest checks. They
recompute freshness without running tests. No checks means no extra output fields.
Repeated files are hashed once per retrieval, under existing repository budgets.

- `passed`: tests actually ran, without failure, skips or expected failures, and
  scoped files did not change during execution.
- `not_verified`: unsuccessful execution, empty suite or skipped/expected-failure
  tests; this deliberately does not claim the behavior is covered.
- `timeout`: the execution exceeded the selected time limit.
- `needs_rerun`: scoped files changed, disappeared or became unreadable, the root
  differs, or the task acquired files not included in that run.

Freshness is limited to the recorded scope. Environment changes, dependencies not
linked to the task, or temporary edits restored between snapshots are not detected.
Passing a test is evidence for that test, not proof that the task's objective is
complete. The agent/user remains responsible for selecting meaningful coverage
and closing the overall task. No watcher, new MCP execution tool or skill
instructions are added.

## Verification in this change

63 targeted tests passed (task checks, standalone experiment, remaining-work
regression, MCP, CLI and metadata boundaries). The final public session-summary
assertion also passed through the real `task verify` invocation: three tests,
zero skips, saved on task 14. That task remains in progress. Changes to scoped
files, added task files and retrieval without subprocess execution are exercised
in temporary repositories. The standalone regression covers failure, skip, empty
suite, timeout, and edits during execution.

This combines execution and recording and reuses the existing task file list.
It does not demonstrate a measured overall time/token improvement.
