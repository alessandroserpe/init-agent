# Conservative Python receiver resolution

2026-10-16. Source implementation; no additional dependency, model or skill text.

The AST extractor now records type-binding facts for direct `obj.method()` calls
when `obj` is either an annotated positional/keyword-only parameter with a simple
class name (including imported aliases and module-qualified classes), or a local
assigned once from a class constructor in the immediate function body.

Type names must come from unambiguous top-level imports or class declarations.
Resolution locates the module and exact class, then the exact directly owned
method in that file. Same-named methods in other classes/files do not qualify.
The existing Python AST parser is retained. These are inferred static relations,
not proof of runtime dispatch: callers can violate annotations, decorators can
replace classes, and external runtime mutation is not analyzed.

## Conservative boundaries

Rerouting a variable, assigning/deleting its attributes, duplicate bindings,
loops, local type-name shadowing, enclosing-scope shadowing, and explicit global
or nonlocal usage suppress these new facts. Nested scopes are scanned
conservatively for competing bindings. Unknown factories, conditional
initialization, captured receivers and nested attribute chains are not inferred.
The new resolver does not search globally by method name.

This first pass does not handle string/union/generic annotations, varargs,
annotated local assignments, inherited methods through typed instances, context
managers, multi-component unaliased module imports, or same-line assignment/call
ordering. Parameters used on the function declaration line are also omitted by
the line-order guard. Existing self/cls/super resolution is unchanged.
Additional dynamic cases such as monkey-patching in another module or arbitrary
setattr calls remain outside this static analysis. Do not treat a resolved edge
as a runtime guarantee or use absent edges to rule out relevance.

Facts are persisted as scalar relation metadata (`receiver_type`,
`receiver_module`, `receiver_binding`) under the existing validation limits.
Resolved edges use resolver `python_typed_receiver`, preserving call-line and
qualified-source evidence for call-path retrieval. No stronger confidence claim
is introduced. Parser walks retain existing cooperative node/time budgets.

## Index and validation

Graph INDEX_VERSION increases from 11 to 12. Existing preparation rebuilds an
older graph automatically; no database deletion is needed. Full-text source
format stays at version 4. Changed source hashes cause ordinary reindexing, and
symbol lookups use the rebuilt graph. Tests verify memory preservation across a
graph-version rebuild and removal of obsolete edges after editing a receiver.

The focused set covers 45 test methods, including existing extraction/resolution
and call-path tests. New receiver tests include positive constructors,
annotations, aliases and module imports, plus sixteen negative variants,
duplicate/local classes, source-search path integration through the new edge,
incremental deletion and index migration. The search integration exercises the
Python search entry point; the preceding call-path tests separately cover MCP.

The same Graphify comparison fixture now yields both
`constructed -> Worker.tick` and `annotated -> Worker.tick` in init-agent,
matching the two previously Graphify-only links. Unknown and rebound calls stay
unresolved. The actual closure/nonlocal call `worker.tick()` in search_tool
remains unresolved, and the selected real maintenance path remains at 8/9 links.
This is a bounded coverage improvement, not a claim that all receiver inference
or repository search has been solved.

Artifacts:
- `experiments/graph-audit/typed-receiver-comparison.json`
- `experiments/graph-audit/typed-path-audit.json`

The Graphify fixture invocation used the same temporary checkout/environment as
the structural audit. Graphify's cache-root-switch warning also occurred; no cache
performance was measured. No new agent benchmark, API spend or token-savings claim.

Final full working-tree suite: 414 tests, OK with two environment skips.
Run included permission for the existing temporary Unix-socket test; no model
or external-service requests were made. Log: /tmp/init-agent-typed-final.log.
