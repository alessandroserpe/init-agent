# Real-use check: exposing inventory fallback

2026-10-16. Task: expose the existing limitation that filesystem inventory does
not apply Git ignore rules when Git inventory is unavailable. This was chosen
from the documented remaining limitations, not from a new external task. The
agent had prior context about the cause; this is not a blind benchmark.

One live `repo_search` call, limit 3, without path restrictions:

> Warn when Git inventory is unavailable and filesystem fallback does not respect gitignore

The unmodified structured response is in `local-search-real-use-02.json`.
It contains 5,922 JavaScript string characters in compact JSON (not tokens),
1,259 source-excerpt characters and 661 note-text characters. MCP transport
also supplied a text copy; these counts cover structured content only.

Results: `tests/test_git_worktree_inventory.py`, `tests/test_ignore_refresh.py`,
and `docs/local-search-real-use-01.md`. The first test and prior diagnostic are
relevant leads, but none is the implementation to change. The second excerpt
contains only `finally: os.chdir(previous)` despite a relevant enclosing symbol.
All three returned memories are stale; none supplied enough evidence to edit.
The any-term candidate cap was reached. No second or reformulated search was made.

Fallback: one `rg` invocation across utils, local_watch, scanner and search_tool
located inventory and warning propagation, alongside a read of local_watch.
One further grouped source/test read resolved the implementation. Later reads
checked test compatibility and local instructions. The task still needed ordinary
search and source verification; no avoided exploration step or token saving is
demonstrated. Prior knowledge influenced the fallback paths, so this is not a
controlled timing comparison. No ranking change follows from this example.

## Useful change completed

Inventory accepts an optional warnings collector. On filesystem fallback it
reports that Git ignore rules are not applied when the root has `.git` metadata
or a root `.gitignore`. A plain folder without either does not receive that
warning. Configured exclusions and Git validation remain unchanged. Nested-only
ignore files in non-Git folders are not detected by this root-level diagnostic.

The maintenance fingerprint collects the diagnostic without another inventory
scan. A diagnostic-state change triggers reconciliation even if the source
fingerprint is identical. Existing MCP warning persistence keeps it visible
on unchanged calls and clears it after recovery. This reports the inventory
observed at fingerprint time; it does not make concurrent filesystem changes
atomic. Direct legacy scanning callers that omit the collector retain their
existing interface and do not gain this diagnostic automatically.

42 focused tests passed: MCP search, local maintenance, linked-worktree inventory
and ignore/refresh. New checks cover fallback, unchanged-state persistence,
recovery without source edits and plain folders with/without root ignore rules.
No LLM benchmark, package install, release or ranking tuning was performed.
