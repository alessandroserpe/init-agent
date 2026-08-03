# Parsing And Optional Tree-sitter

`init-agent` keeps parsing local and dependency-light by default.

## Default Parsers

- Python uses the standard-library `ast` module.
- PHP uses the built-in lightweight parser.
- JavaScript, TypeScript, Go, Rust, Markdown and config files use lightweight
  built-in extraction.

The index stores metadata, symbols, relations, file hashes and estimates. It
does not store full source code.

## Resolved File And Symbol Relations

Mapping keeps the raw extracted relation and runs a second resolution pass.
When a target can be identified without ambiguity, SQLite receives an
additional relation with `target_type = resolved_file`.

Python and PHP also retain qualified symbol identity and the callable scope in
which a relation occurred. When both ends can be identified without ambiguity,
the resolver materializes a `source_type = symbol` relation with
`target_type = resolved_symbol`. This distinguishes, for example, which method
called a shared helper instead of reporting only the caller file.

Resolution currently covers:

- Python modules, imported symbols, scoped calls, route handlers and rendered
  templates;
- PHP include/require paths, including common static `__DIR__` expressions,
  and procedural calls inside the same include/require component;
- relative JavaScript and TypeScript module paths already visible to the
  lightweight extractor.

The deeper symbol layer currently covers:

- Python function and method calls attributed to qualified callable scopes;
- Python class inheritance, including imported base classes;
- PHP function and method calls inside resolvable include/require components;
- PHP class inheritance and implemented interfaces;
- derived file-level inheritance edges used by `trace` and ranking.

Raw file relations carry an optional `context_symbol_id`; this avoids storing
duplicate raw symbol edges while preserving the callable that produced the
relation. Only resolved symbol edges are materialized separately.

Context ranking consumes this deeper layer through a bounded structural
reranker. It keeps the existing lexical score, starts from a small seed set,
traverses one resolved hop, penalizes high fan-out and caps propagated scores
below their seed. For symptom queries, a strongly matching test method can
promote the production function it calls. Matching is based on the leaf method
name rather than a generic test-class prefix, and test inheritance is not used
as cause evidence. File-wide imports remain a weaker fallback, so a large test
module does not automatically promote every imported module.

Ambiguous calls remain unresolved instead of being connected to every symbol
with the same name. `trace` prefers resolved edges on current indexes and uses
nominal fallback traversal only for older indexes. Raw relations remain in the
database for inspection and future resolver improvements.

Static resolution is deliberately conservative. Dynamic dispatch, reflection,
runtime imports/includes and dependency-injection containers may remain
unresolved rather than being linked to every same-named symbol.

## Optional PHP Tree-sitter

PHP projects can opt into a more precise parser:

```bash
pipx inject init-agent tree-sitter tree-sitter-php
```

After installing the optional packages, remap the project:

```bash
init-agent map
```

When available, PHP mapping uses tree-sitter for classes, methods, traits,
interfaces, enums, calls and includes. It still merges in built-in extraction
for constants and route-like signals.

If tree-sitter is not installed or fails on a file, init-agent automatically
falls back to the built-in PHP parser.

## Why Optional

Tree-sitter improves precision for languages where robust parsing is not
available in the Python standard library, but it adds compiled dependencies.
Keeping it optional preserves the default install:

- Python 3.11+
- no required runtime dependencies
- local-only indexing
