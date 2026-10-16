# Structural audit: init-agent and Graphify

2026-10-16. Graphify branch v8, commit
`86c57be8204673c2a1b9849a3292a7dd3ab373d8`, package metadata 0.9.92.
Public source cloned to /tmp/graphify-audit; minimal Python parsing dependencies
installed only in /tmp/graphify-audit-venv. No Graphify skill, hooks, MCP setup,
API keys, models or production init-agent changes.

## Finding 1: the full-text search does not perform graph retrieval

`init_agent/local_search.py::_source_candidates` selects chunks by exact symbol
or path, all-term/any-term FTS, proximity and BM25. Only after that ranking,
`search` attaches up to four resolved *file* links ordered by confidence. There
is no graph expansion of candidates or query-specific call path in this tool.
The original context/reading-plan machinery is different: `context_builder.py`
has structural seeding/scoring, and `trace.py` already traverses resolved links.
Do not claim that all of init-agent ignores its graph. The newer FTS route and
older structural route are separate retrieval paths.

Graphify `serve.py::_query_graph_text` scores graph nodes, picks seeds (or accepts
explicit seeds), then `_render_query` traverses with BFS/DFS and returns a bounded
subgraph. `_bfs` avoids transit through very high-degree hubs unless selected as
seeds. Its default lexical seeding is still heuristic, not natural-language
understanding. Centrality is not proof of task relevance. Its text budget is an
approximate character-based token budget. No end-to-end query comparison was run.

Source: https://github.com/Graphify-Labs/graphify/blob/86c57be8204673c2a1b9849a3292a7dd3ab373d8/graphify/serve.py

## Finding 2: existing extraction is useful but has a resolvable gap

`python3 -m experiments.graph_path_audit` copies the current init_agent package
into a temporary directory, initializes a fresh graph/FTS index and inspects nine
manually source-verified call links in the real maintenance path. This is a
selected diagnostic path, not representative recall for the whole repository.

66 indexed files, 1,118 symbols, 12,748 relations. All requested endpoint symbols
and all nine raw call records are present. Eight of nine symbol links resolve:

- `handle -> search`: present.
- `Maintainer.tick -> fingerprint`: present.
- `fingerprint -> iter_project_files`: present.
- `iter_project_files -> iter_indexable_files`: present.
- `iter_indexable_files -> _git_indexable_paths`: present.
- `_git_indexable_paths -> run_git_read`: present.
- `Maintainer.tick -> prepare_repository`: present.
- `Maintainer.tick -> update_search_index`: present.
- `handle -> Maintainer.tick` through `worker.tick()`: absent.

The Python extractor records the call and qualifier but does not track instance
bindings in Assign/AnnAssign. The symbol resolver explicitly skips Python
receivers that are neither self/cls/super nor imported modules. This prevents
unsafe name-only guesses, but also loses some statically resolvable instance calls.
The real missing edge uses a nonlocal variable initialized conditionally inside
a nested handler: it is more difficult than a simple local constructor binding.

Raw output: `experiments/graph-audit/init-agent.json`. The source-only copy excludes
tests, diagnostic docs and user notes. Its search results therefore cannot be
compared directly to prior full-repository ranking results. In particular, the
recent warning text also contains the literal Git/fallback query terms.

## Finding 3: Graphify demonstrates a bounded receiver-resolution improvement

Run in the isolated environment:

```
/tmp/graphify-audit-venv/bin/python -m experiments.graph_receiver_comparison /tmp/graphify-audit
```

The same tiny package defines Worker.tick and Other.tick, then calls through:

| Caller | init-agent symbol edge | Graphify edge |
| --- | --- | --- |
| Local `worker = Worker()` | absent | Worker.tick, INFERRED |
| Parameter `worker: Worker` | absent | Worker.tick, INFERRED |
| Unknown parameter type | absent | absent |
| Annotated parameter reassigned to Other | absent | absent |

Graphify's result points to `pkg_worker_worker_tick`, not merely an arbitrary
same-named method. It has extraction/type-binding support and a dedicated Python
member-call resolver. The unknown/rebound cases remain unresolved conservatively.
The actual init-agent package was also parsed by Graphify (1,220 nodes, 5,186
edges); it did NOT produce the missing search_tool -> tick edge. Raw node/edge
counts across the two tools are not comparable because the schemas differ.
Graphify emitted a cache-root-switch warning during the two temporary scans;
separate cache roots were used, but the run does not measure cache performance.

Sources:
https://github.com/Graphify-Labs/graphify/blob/86c57be8204673c2a1b9849a3292a7dd3ab373d8/graphify/extract.py
https://github.com/Graphify-Labs/graphify/blob/86c57be8204673c2a1b9849a3292a7dd3ab373d8/tests/test_python_typed_receiver_calls.py

## Interpretation and next implementation boundary

The user's proposed structural approach is technically supported. Prior failures
of the FTS tool do not refute it. There is already useful graph information in
init-agent; restarting from zero or blindly replacing the parser is unjustified.
Python's built-in AST is adequate for the Python cases above. Tree-sitter alone
does not supply receiver resolution: the binding/resolution logic matters.

The concrete next experiment should connect FTS/symbol seed selection to the
existing resolved-symbol graph, returning a short path with call-site evidence,
rather than four generic file links. First use already-resolved paths; separately
add conservative local constructor/annotated-parameter resolution with negative
cases for reassignment, shadowing and same-name classes. Keep nonlocal/conditional
receiver inference explicitly unresolved until supported by evidence.

Evaluate extraction coverage, edge correctness and retrieval separately. Include
new tasks beyond this maintenance path, relevant branches and lexical decoys,
and compare a fixed evidence budget with ordinary search. Do not infer semantic
irrelevance from missing edges or equate global centrality with task relevance.
A useful result must remove actual exploration steps, not just increase edge count.
No runtime benefit, token saving or generic ranking superiority is established
by this audit. Graphify's published benchmark and marketing claims were not
reproduced and are not evidence of savings for this repository.
