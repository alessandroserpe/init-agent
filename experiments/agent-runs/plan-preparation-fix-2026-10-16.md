# Initial plan failure: diagnosis and fix

The completed subscription pilot is unchanged. This follow-up reproduced its
initial-plan failures without model calls and fixed a duplicated context search
in the CLI preparation path. This is not a new end-to-end agent benchmark.

## Root cause

`repo_reading_plan(prepare=True)` called `run_query("reading plan " + query)`
only to obtain preparation metadata. That call also computed a full context
ranking which was discarded. `build_reading_plan` then computed another ranking.
The CLI shares one operation budget, so the two passes exhausted its one-million
step limit. MCP's `prepare=False` path did not incur this duplication.

The original explanation that full-task requests exhausted the budget was an
observation, not the cause: each of the same five requests succeeded through
the direct reading-plan builder. Query shortening in the agent runs coincided
with switching from CLI preparation to MCP; those logs alone could not establish
that shortening was what enabled recovery.

`prepare_repository` now performs initialization, mapping/refresh and Git metadata
preparation without an unused search. Both `run_query` and the reading-plan tool
reuse it. A failed initialization or map returns an empty unsaved plan, instead
of proceeding to build one. No work limits or ranking weights were increased.

## Historical reproduction

Fresh indexes were prepared from the same five pinned base snapshots, with the
current engine imported from the controller, no existing user memory and the
original full task descriptions. The enclosing shared budget matches CLI use.

| Task | Before | After: steps used | After: nonempty plan |
| --- | ---: | ---: | --- |
| Dashboard freshness | Failed at 1,000,001 | 565,199 | Yes |
| Resumed sessions | Failed at 1,000,001 | 592,633 | Yes |
| Skill backups | Failed at 1,000,001 | 507,214 | Yes |
| Deleted targets | Failed at 1,000,001 | 568,148 | Yes |
| Imported aliases | Failed at 1,000,001 | 516,395 | Yes |

This fixes plan availability, not all retrieval quality. After the fix, a
reference implementation target appears among the first three suggestions for
three of the five tasks. Backup discovery still favors skill documentation and
its tests; deleted-target handling still favors CLI/MCP dispatch files. For the
backup task, the direct context pack puts `skill_installer.py` eighth, and final
fusion drops it outside the first ten. Raw trace contributions for the skill
documents exceed the normalized graph contribution. These are concrete ranking
weaknesses requiring separate validation, not proof of a broken file scanner.

The narrower plans used in the original agent runs also vary with query wording.
The two failed alias runs suggest `symbol_extractor.py` second but put CLI or
context-builder files first; the successful run puts `query.py` first. That
association is worth investigating, but does not prove that suggestion order
caused the different final solutions.

## Why input tokens increased

On the original ten both-correct pairs, the median relative input increase was
42.2% including cache and 4.1% excluding cache, with three additional tool calls
at the paired median. These percentages have different denominators and must
not be subtracted to assign a share of the increase to cache.

The following additional audit uses **all 15 runs per arm**, in UTF-8 bytes,
not tokens. MCP response size is measured by JSON serialization of each logged
`tools/call` response and summing within each run.

| Median per run | Baseline | Assisted |
| --- | ---: | ---: |
| Initial prompt bytes | 574 | 8,562 |
| Logged command-output bytes | 136,688 | 108,814 |
| Serialized MCP tool-response bytes | 0 | 17,003 |

The assisted prompt adds the orientation skill and initial-plan error. It also
exposes MCP tool definitions and adds MCP responses and subsequent interaction
history. Repeated model steps can process that context again, often cached.
More command-output bytes are **not** supported as the explanation: that median
was lower in the assisted arm. Command-output bytes are not exact file-read
counts or total model context.

The logs report aggregate turn usage; they cannot allocate the 42.2% between
tool schemas, skill instructions, retries and different agent decisions. The
duplicate local search itself uses no LLM tokens. Fixing it removes a failure
and potential recovery overhead, but no reduction in agent token consumption
has yet been measured after this patch.

## Validation

- 86 preparation, CLI, context and repository-budget tests passed.
- 62 MCP, resource-budget, freshness, refresh and preparation tests passed
  (the three new preparation tests occur in both groups).
- The new synthetic full-plan budget regression reproduces the step-limit
  failure with the pre-fix implementation and passes with the corrected code.
- Initialization/refresh and failed-preparation behavior are covered explicitly.
- The five historical reproductions now return nonempty plans at unchanged limits.
- `git diff --check` passed. No model runs, changed benchmark outcomes or changed
  ranking coefficients are claimed by this follow-up.

Private reproduction output and prompt-audit figures are retained under
`results/plan-diagnosis-20261016/`.
