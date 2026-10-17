# Remaining work: real fix and test discovery outcome

The installed `repo_test_candidates` was called once for
`init_agent.tasks.update_task`, limit 2. It scanned 54 test files and returned
`no_direct_test_found`, without warnings. Existing MCP and CLI task tests invoke
wrappers rather than importing this function directly. Manual search was needed:
the lookup did not replace any work on this change. No further discovery calls
were made to try to obtain a favorable result.

The actual defect was append-only remaining work. Updating or closing a task
could not remove resolved items. The regression in `tests/test_task_remaining.py`
failed before the fix for Python, MCP and both CLI entry points.

Current semantics:
- Update: omitted `remaining` preserves it; an explicit list replaces it; `[]`
  clears it. In either CLI, `--remaining ''` clears the list.
- Close: only explicitly supplied follow-up remains; omission clears it.
- Progress notes still append follow-up and preserve historical evidence.
- Other linked metadata (including performed tests) remains cumulative.

This changes the previous append semantics for update/close. Callers that want
to append work should add a progress note or send the complete current list.
Existing saved tasks are not migrated or rewritten automatically.

Validation: `python3 -m unittest tests.test_task_remaining tests.test_mcp
 tests.test_cli_tools` passed all 42 tests after the fix. The lifecycle regression
also checks that historical note contents and performed tests survive clearing.
No skill changes, installation or commit performed for this fix.
