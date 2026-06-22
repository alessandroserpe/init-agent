# Security And Privacy

`init-agent` is local-first.

- No built-in LLM execution.
- No external services contacted by the CLI.
- No repository contents sent anywhere.
- No full source code stored in SQLite.
- Generated metadata lives under `.agent/`.

## What Is Stored

The SQLite database stores metadata such as:

- project metadata
- file paths, roles, languages, hashes and timestamps
- extracted symbol names and signatures
- lightweight relations
- recent Git commit metadata
- local orientation feedback

It intentionally does not store full file contents.

## Graph Export

`init-agent export --json` exports the indexed metadata graph for external
tools. It includes paths, symbols, relations, Git metadata, feedback and run
summaries, but not full source file contents.

## MCP Server

`init-agent mcp` exposes the same local metadata contracts over stdio for
MCP-capable agents. It does not contact external services and does not execute
an LLM. The tools are read-only for project source files, but they may create
or update `.agent/` to keep the local SQLite index fresh.

## When Files Are Read

File contents may be read locally during:

- `map`, to extract metadata, symbols and relations
- `refresh`, for changed or new files
- `estimate`, to count characters for token estimates

## Generated Files

In most projects, `.agent/` should stay ignored and should not be committed.

You can inspect the local database directly:

```bash
sqlite3 .agent/graph.sqlite ".tables"
sqlite3 .agent/graph.sqlite "select path, language, role from files limit 10;"
```
