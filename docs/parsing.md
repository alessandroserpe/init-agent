# Parsing And Optional Tree-sitter

`init-agent` keeps parsing local and dependency-light by default.

## Default Parsers

- Python uses the standard-library `ast` module.
- PHP uses the built-in lightweight parser.
- JavaScript, TypeScript, Go, Rust, Markdown and config files use lightweight
  built-in extraction.

The index stores metadata, symbols, relations, file hashes and estimates. It
does not store full source code.

## Resolved File Relations

Mapping keeps the raw extracted relation and runs a second resolution pass.
When a target can be identified without ambiguity, SQLite receives an
additional relation with `target_type = resolved_file`.

Resolution currently covers:

- Python modules, imported symbols, scoped calls, route handlers and rendered
  templates;
- PHP include/require paths, including common static `__DIR__` expressions,
  and procedural calls inside the same include/require component;
- relative JavaScript and TypeScript module paths already visible to the
  lightweight extractor.

Ambiguous calls remain unresolved instead of being connected to every symbol
with the same name. `trace` prefers resolved edges on current indexes and uses
nominal fallback traversal only for older indexes. Raw relations remain in the
database for inspection and future resolver improvements.

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
