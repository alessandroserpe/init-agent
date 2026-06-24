# Parsing And Optional Tree-sitter

`init-agent` keeps parsing local and dependency-light by default.

## Default Parsers

- Python uses the standard-library `ast` module.
- PHP uses the built-in lightweight parser.
- JavaScript, TypeScript, Go, Rust, Markdown and config files use lightweight
  built-in extraction.

The index stores metadata, symbols, relations, file hashes and estimates. It
does not store full source code.

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

