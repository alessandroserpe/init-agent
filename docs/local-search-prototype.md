# Local search prototype

Branch `experiment/local-maintenance`. No model/API calls, external search
service or added Python dependencies. SQLite must provide FTS5 (verified on the
Python interpreter used for these tests).

## How it works

The maintenance worker builds a local SQLite full-text index alongside the graph.
Only changed graph-indexed text files are reindexed. Source is split into 24-line
windows with four-line overlap. File/symbol names and source content are indexed;
identifiers are split at underscores and camel case. FTS5's Porter tokenizer and
BM25 retrieve and rank lexical matches. This is lexical retrieval, not natural
language understanding or automatic Italian-to-English translation.

A query returns up to three distinct source files by default (maximum ten), with
source hash, line range, up to twelve excerpt lines/1,400 characters, up to three
symbols and four graph links per file. Candidate retrieval now combines three bounded channels (up to 80 chunks each):
all query terms, any query term, and exact symbol/path matches. Exact definitions
exclude documentation headings and command examples. Results prefer exact targets,
then all-term coverage, literal term proximity and BM25. Lexical channels now keep at most two chunks per file before applying the
global cap, to prevent a large document from filling every candidate slot.
The cap can still omit relevant files in a large matching corpus. Truncation/candidate limits
are reported. Hash verification omits changed/missing source candidates rather
than presenting their indexed excerpt as current. Links remain graph evidence,
not proof of semantic correctness, test coverage or current target content.

Optional repeated `--path-prefix` restricts source results to repository-relative
paths, analogous to choosing directories for an ordinary search. It does not
filter memories. There is no implicit preference for source over documentation.

## Persistent SQL notes

An external-content FTS5 index covers `agent_notes.note`, topic, original query,
tags and path. Existing notes are indexed on installation; insert/update/delete
triggers keep it synchronized in the same transaction as subsequent note writes.
This works even when the maintenance process is idle or stopped after setup.

Up to three memory hits are returned separately with note id, source, evidence,
recorded content hash, timestamp and live stale status. Notes for changed files
remain discoverable but marked stale; repository notes have unknown/not-applicable
file freshness, not a manufactured fresh status. Text is capped at 1,000 characters
per note. The prototype does not synthesize notes after edits or search arbitrary
SQL tables. Tasks, task notes and plan events are not yet in this full-text index.

## Usage

From the isolated worktree:

```sh
python3 -m init_agent.local_watch --root /path/to/project --once
python3 -m init_agent.local_search 'backup skill' --root /path/to/project --path-prefix init_agent/
```

Leave `local_watch` running without `--once` for subsequent automatic maintenance.
The direct query interface only reads; it does not initialize/update the index.
The function `local_search.search` remains callable from Python. MCP now exposes
`repo_search` in core/full profiles: its wrapper performs maintenance before
retrieval and reuses unchanged state within the server process. Thus MCP callers
do not need the manual preparation commands above. See [MCP](mcp.md).

Source chunks are now persisted in the private `.agent/graph.sqlite`, unlike the
previous metadata-only graph. Existing file exclusions apply, with additional
exclusion of `.env*`, common credential filenames and key/certificate extensions.
This is not a general secret detector for arbitrary source or existing notes.
Keep `.agent` local. The source index includes only graph-indexed readable text,
so files omitted by parsing/index budgets and oversized/non-text files remain
outside this prototype. A skipped update is reported, not claimed complete.

## Verification and diagnostic replay

59 maintenance/search/memory/refresh/relation/freshness tests passed after the
ranking revision. See [ranking revision](local-search-ranking.md) for current
measurements; the replay below describes the earlier BM25-only baseline. Tests include
body-only matches, snake/camel identifiers, precise excerpts, graph links,
read-only querying, exclusions, stale candidate omission and deletion, existing
and newly written SQL notes, update/delete triggers, and unchanged evidence hashes.

`python3 -m experiments.local_search_replay` replays four keyword sets taken from
saved agent command traces on an exported snapshot of this worktree's HEAD. Pipe
alternatives are normalized to words; the new engine is not executing the old
regular expressions. This is a post-hoc diagnostic on revision `14636ac`, not a
rerun of the historical agent tasks, a held-out benchmark, or a token comparison.
One earlier exploratory pass used adapted terms; these are not the reported final
queries. Results are retained in `local-search-replay.json`.

Observed locally: 129 files indexed (graph plus search) in about 1.08 seconds;
four unscoped queries took about 4.8–5.4 ms each. Three source hits produced about
3.7–4.9 KB JSON, with no stored notes in that snapshot. These timings are single
small-repository observations and do not establish agent savings.

| Query family | Unscoped top source | Code-scoped top source | Reference implementation in code-scoped top 3? |
| --- | --- | --- | --- |
| Backup / skills | skills/README.md | skill_installer.py | Yes |
| Related files / callers | tests/test_index_context.py | agent_tools.py | No: relation_resolver.py absent |
| Freshness / memory | tests/test_memory.py | index_health.py | No: web_ui.py absent |
| Overview / unindexed / removed | tests/test_index_health.py | index_health.py | Yes |

These reference files are diagnostic labels, not proof that other results are
useless. The old scorer's top three and all new results are in the JSON. Raw
full-text ranking is not uniformly better: broad queries can favor documentation
or related helpers. Adding source evidence and SQL memory retrieval is working;
claiming general superiority or reduced LLM work would be premature. Do not tune
repeatedly against these four examples. Next evaluation should focus on whether
returned evidence actually replaces exploration steps, with a fixed output budget.


## Scope-aware index integration (2026-10-16)

The experimental maintenance path now uses `init_agent.search_passages`:
24-line windows with stride 20 stay inside parser-provided symbol intervals.
Missing or invalid end lines label only the declaration line. Existing output
limits and ranking rules remain unchanged; no model or skill prompt is added.

`search_index_meta` stores source index version 4. The next maintenance pass
rebuilds an unversioned/older source index, even with unchanged source hashes.
Source chunks, indexed hashes and the version are committed in one transaction;
an unexpected failure rolls them back together. Notes and their FTS triggers
are preserved. A newer index version is refused rather than downgraded. Files
that cannot be read or whose hashes disagree are omitted with the existing
warning and retried on a later pass. Graph refresh and SQL-note setup remain
outside the source-index transaction; this is not whole-repository atomicity.

No manual database deletion or skill sync is required. From this worktree,
`python3 -m init_agent.local_watch --root /path/to/repo --once` performs the
maintenance/migration. The CLI/watch path remains experimental; the MCP wrapper now also exposes it
as `repo_search` with maintenance on demand.

69 focused tests pass, including unchanged-file migration, note preservation,
no-op subsequent maintenance, failure rollback, future-version refusal and
incremental add/edit/delete equivalence to full rebuild. Cost and relevance
limitations remain in `local-search-scope-cost.md` and
`local-search-scope-passages.md`; their measurements predate integration.
Historical scope experiments explicitly recreate fixed-window baselines so
rerunning them does not silently compare the integrated index to itself.


## MCP on-demand integration

`repo_search` is available in core/full MCP profiles. It owns a per-server
maintenance instance and performs initialization and reconciliation on demand,
under the same advisory lock as the foreground watcher. Invalid input is
rejected before creating metadata. An unchanged request does not remap files;
reconciliation is due after 60 seconds and occurs on the next request. Stored
notes remain independently freshness-checked. Indexing warnings accompany
results; failures and work-budget exhaustion produce explicit MCP errors.
The existing `repo_graph_search` contract and the skill text are unchanged.

The complete working-tree suite passes 390 tests with two skips. Dedicated
checks exercise first-call initialization, unchanged-state reuse, edits and
deletion, stale notes, rejected inputs without metadata writes, lock contention,
maintenance warnings/failures, budget exhaustion/recovery and real stdio JSON
framing. A fresh exported init-agent snapshot also succeeds through the MCP
entry point, including first initialization and subsequent calls. No model
benchmark was run. Restart the MCP server (or start a new Codex session) after
updating the package so the client discovers the new tool; skill sync is not
needed for this change.


## Bounded indexing correction

Version 3 additionally limits passages to 8192 characters while preserving line
ranges. A source with an individually oversized line or metadata field is skipped
as a whole, without leaving partially inserted hits; maintenance reports the
skipped file. The MCP tool preserves incomplete-index warnings on later unchanged
calls. This is a coverage limit, not a claim that excluded files are irrelevant.

Updates delete retired chunks in one SQL pass using a temporary set of changed
or removed paths. New files require no prior deletion. This avoids repeated
full-table scans of the unindexed FTS path column. Source rows and their version
still use the same transaction and rollback behavior. Work budgets are unchanged.


## Unicode normalization

Source index version 4 uses NFC Unicode normalization for full-text queries and
source passages. It preserves accented/non-Latin words and retains the previous
ASCII identifier splitting behavior. Existing function-word filtering now sees
`perché` intact rather than the accidental fragment `perch`. No translation,
new synonym dictionary or ranking weights are introduced. The legacy graph
normalizer and its index version remain unchanged. Source index versions below
4 are rebuilt automatically; stored note text is not rewritten.

See [normalization comparison](local-search-normalization.md): this corrects
text loss, but does not resolve the broad Italian task in the fixed-snapshot
comparison. The result must not be presented as a generic ranking improvement.

## Experimental call-path evidence

Source search now expands the first lexical hit through existing resolved-symbol
calls, with at most two short, freshness-checked paths. When present, call-site
paths replace the generic file links; lexical ranking remains unchanged.
Ambiguous branches are reported instead of guessed. See
[call-path behavior and measurements](local-search-call-paths.md) for bounds,
response fields, tests and the limited same-index diagnostic comparison.

## Python receiver facts

Graph index version 12 adds conservative local-constructor and annotated-parameter
method resolution. These edges feed the existing call-path retrieval; ambiguous
or unsupported receiver cases remain unresolved. See
[receiver scope and verification](python-typed-receivers.md).
