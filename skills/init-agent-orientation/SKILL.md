---
name: init-agent-orientation
description: Use local repository context when the implementation location is unclear, dependencies remain ambiguous, or prior work and decisions need to be recovered across sessions.
---

# Init Agent Orientation

Use only the operation that answers a concrete need. Skip orientation when the
implementation is already located; ordinary search and reads need no prior tool
call. Stop consulting tools once you have enough evidence to act.

- **Unknown starting point:** consider `repo_reading_plan` with a specific query
  and `read_budget=3`. Reuse a supplied current plan; do not request it again.
  Use `repo_overview` only for missing broad context. Verify suggestions in source;
  if they miss the target, use direct search rather than a mandatory recovery loop.
- **Unclear dependencies:** use `repo_related_file` or `repo_symbol_callers` for a
  known file/symbol when ordinary exploration leaves an ambiguity. Keep compact
  output unless missing evidence requires details.
- **Resuming work:** consult relevant memory with `repo_memory_search` and recover
  existing tasks when needed. Reading plans locate code; persistent tasks track
  unfinished work. Use task tools through CLI help or the full MCP profile only
  when continuity is useful; do not duplicate another maintained work plan.
- **Worth retaining:** use `repo_memory_add` for verified decisions, constraints
  or discoveries costly to reconstruct. Keep notes short, scoped and supported
  by truthful evidence; omit routine narration, duplicates and secrets.

Before relying on stored context, check available freshness warnings. Verify
stale notes against live source; fresh means unchanged, not necessarily correct.
Revalidate only after verification. Missing indexes or stale graph data may need
`init-agent run --overview --markdown` before graph use; prepare only if that
lookup is worthwhile and CLI is available, otherwise use direct source search.

If a reading plan was used, finish it once with `repo_reading_plan_finish`: plan
id, ordered read paths and verified classifications (central, support, created,
verification, noisy, missing). Do not duplicate feedback. Use a non-real `kind`
for experiments or planning. Use `repo_session_close` when a continuity check
helps a handoff; it is advisory, not required after every edit. Keep `.agent/`
local. Do not add telemetry calls, install hooks or enable delegation implicitly.
