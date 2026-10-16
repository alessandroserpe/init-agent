# Local maintenance prototype

Experimental branch: `experiment/local-maintenance`, based on `14636ac`.
It intentionally excludes uncommitted work in the original checkout.

Run from this worktree, with the same Python 3.11+ used for init-agent:

```sh
python3 -m init_agent.local_watch --root /absolute/path/to/project
```

The foreground process initializes the selected project, polls file metadata
(default: every 2 seconds), and calls the existing preparation/refresh pipeline
on changes. A full reconciliation every 60 seconds catches changes missed by
metadata polling. Ctrl+C stops it; nothing is installed into editor, shell, OS
startup or Codex. To run only one reconciliation:

```sh
python3 -m init_agent.local_watch --root /absolute/path/to/project --once
```

Output is JSON Lines. `.agent/maintenance.jsonl` records indexed file additions,
updates and removals, status/warnings and elapsed time; path samples are capped
at 50 per category. Log rotation retains at most two approximately 1 MB segments.
These are observed index changes, not explanations of developer intent; a parse
failure can remove a file from the index without deleting it on disk.

A per-root advisory lock prevents two prototype workers. The lock is released
on exit, even if the file remains. Existing metadata access/exclusions and work
budgets are reused; each pass gets its own budget. Idle polls do not write the
index. Periodic reconciliation intentionally can write run/Git metadata even
when no source content changed. Configuration changes and missing databases
trigger preparation. A source edit during indexing is checked again next pass.

Memory evidence is never automatically revalidated: the existing read-time hash
check continues to flag notes referring to earlier content. Existing read-only
agent APIs can consult the refreshed graph without asking an LLM to maintain it.

## Scope and limits

This is a macOS/Linux foreground polling prototype, not a production daemon or
native filesystem watcher. It scans paths during polling and hashes all indexed
files during refresh; graph relation resolution remains global. The subsequent search prototype adds lexical retrieval and SQL note indexing;
see [local-search-prototype.md](local-search-prototype.md). Initial graph
enrichment and semantic understanding remain outside this experiment.

The lock coordinates only these workers: do not run manual map/refresh writers
against the same root concurrently. There is no new atomic multi-stage index
publication protocol; existing SQLite behavior applies. Readers during updates
may need to retry. No Git operation is performed, but the existing preparation
pipeline reads Git metadata during reconciliation.

Unexpected exceptions stop the process with a JSON error and nonzero exit;
structured preparation failures are reported and retried next interval. Status
is not a promise of exhaustive parsing or semantic completeness. No automatic
project discovery, shell integration, background installation or remote service
is enabled. OS event subscriptions, backoff and affected-subgraph updates remain
future work after validating the maintenance contract.

## Verification

`python3 -m unittest tests.test_local_watch -v`

Tests cover:
- clean-map equivalence of file hashes, symbols/signatures and resolved file
  edges after creation, same-size editing with restored mtime, rename and deletion;
- resolving an import after its target is created;
- no index writes during idle polling;
- periodic recovery when the metadata change signal is missed, and offline edits
  discovered by a new worker;
- exclusive worker ownership and lock release;
- preserved memory evidence/staleness and updated symbol lookup without prepare;
- a real subprocess observing edits and stopping cleanly with SIGINT.

No LLM/model calls are involved. These tests establish local maintenance behavior,
not lower agent token usage or an advantage over ordinary agent search.
