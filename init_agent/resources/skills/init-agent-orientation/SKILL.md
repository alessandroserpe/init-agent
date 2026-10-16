---
name: init-agent-orientation
description: Orient coding work in an unfamiliar repository and reuse verified local context across tasks. Use reading plans, targeted graph queries, feedback and memory; skip trivial edits with known files.
---

# Init Agent Orientation

Use the smallest useful loop. Do not call every available command. Suggestions
are hypotheses: verify source and tests before editing or claiming correctness.

## Orient and investigate

- Reuse a supplied, current reading plan and its id; do not request it again.
  Otherwise call `repo_reading_plan` with a concrete query and `read_budget=3`.
  Use `repo_overview` only when broad repository context is missing.
- Read the `read_now` files. If they miss the target, narrow the query to a
  symptom/symbol, then use `repo_related_file` or `repo_symbol_callers` as needed.
  Only then broaden filesystem exploration. Stop orientation once the relevant
  implementation is found. Keep compact output; request `include_details=true`
  only for missing evidence, not by default.
- Check `preparation.index_health`. Missing/empty indexes need preparation;
  stale indexes need refresh before graph-sensitive work. If CLI is available,
  run `init-agent run --overview --markdown` once from the repository root.
  Do not repeatedly rebuild or silently treat stale results as current.
  If preparation is unavailable, disclose it and use direct source searches.

## Finish and retain useful context

Call `repo_reading_plan_finish` once after verification, using the plan id,
ordered `read` paths and truthful classifications:
`central` = existing implementation owner; `support` = supporting existing file;
`created` = new file; `verification` = tests/docs used to verify;
`noisy` = suggested but irrelevant; `missing` = important existing file omitted.
This records feedback; do not duplicate it separately. Set a non-real `kind`
for experiments, diagnostics, smoke tests, planning or documentation-only work.

Use `repo_memory_search` when returning to a known area. Verify stale notes
against live files; fresh means unchanged, not necessarily correct.
Use `repo_memory_add` only for a verified, durable fact that saves future work:
short note, topic, tags and truthful evidence. Use file scope for file behavior,
repo scope for project decisions. Do not store source snippets, secrets, personal
data, speculative claims, task narration or duplicate notes. Revalidate stale
memory only after checking it; editing a note alone does not refresh its evidence.

After non-trivial work call `repo_session_close`; its checklist is advisory.
Report actual verification and remaining issues. Keep `.agent/` local.

## Optional operations

Keep task administration, scorecards and memory maintenance outside the default
loop; consult the relevant CLI `--help` or full-profile tool schema when needed.
Delegation advice is disabled by default; request `delegate=true` only for useful,
independent workstreams. Review worker evidence before accepting their outcomes.
Do not add telemetry calls or install trajectory hooks implicitly. Trajectory
is redacted metadata, not prompts, source, tool output or model reasoning;
unknown outcomes are not successes. If doctor reports a skill mismatch, tell
the user to run `init-agent sync`; do not check remote updates implicitly.
