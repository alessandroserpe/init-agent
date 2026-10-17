# Experimental behavior evidence release note

`repo_trace` has an opt-in static evidence mode for inspecting a narrow set of
repository paths. Enable it with `evidence: true`; an explicit anchor can focus
the trace on an indexed path and optional qualified symbol:

```json
{
  "query": "trace request handling",
  "evidence": true,
  "anchor": {"path": "src/handler.py", "symbol": "Handler.run"}
}
```

Evidence mode is experimental. It reports static source relationships with
provenance and gaps; it never observes execution. Python admission focuses on
conservative direct lexical calls and explicit imports. PHP can report
qualified namespace function calls and include/require paths when structural
analysis is available; tree-sitter PHP is optional, and regex fallback is not
accepted as structural evidence. TypeScript uses an optional isolated,
pinned-compiler worker (`npm ci` in `init_agent/typescript_worker/`) for
compiler-resolved local imports, direct calls and constructions. If the worker
or compiler is unavailable, TypeScript structural evidence is unavailable.

Before returning an edge, the trace checks source and target hashes against
their indexed evidence. TypeScript also checks hashes for the files used by its
analysis. Changed or missing inputs become gaps. These checks do not establish
that an edge runs at runtime or that returned paths are exhaustive.

Receiver dispatch such as typed receiver calls and `self`/`cls`/`super` remains
unverified because overrides and dynamic dispatch can change the target. Such
relationships are not presented as resolved evidence. Generic unresolved-call
hints may include a syntactic target name and source line, but they do not
identify a receiver type or choose an override.

Large-index reads and per-file relation rows are capped and report gaps when
those limits are reached. A missing edge therefore does not prove the source
has no such relationship. The request remains bounded by work, time, file and
byte budgets; budget exhaustion is reported as a gap where detected.

Independent-session utility evaluation is pending. There are no claims here of
reduced model context, better task outcomes or faster completion. No independent
novel-task sessions were performed: the current work covered correctness
fixtures and integration behavior, not a utility study. Keep evidence mode
opt-in until independent task sessions establish practical utility. See [the
behavior evidence evaluation protocol](behavior-evidence-evaluation.md).

The equivalent CLI is:

```sh
init-agent trace "request handling" --evidence --anchor-path src/handler.py --anchor-symbol Handler.run --json
```

Dependencies are installed only by an explicit operator command, never by a
search, trace or mapping request. The TypeScript worker does not load project
scripts or plugins. Project references, dynamic callbacks and instance dispatch
remain gaps. PHP grouped imports and dynamic dispatch are unsupported. On hosts
where native resource limits cannot be enforced, PHP uses the declared fallback.
