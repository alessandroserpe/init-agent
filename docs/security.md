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
