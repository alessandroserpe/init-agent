# Security And Privacy

`init-agent` is local-first.

- No built-in LLM execution.
- Mapping, memory and MCP operations do not contact external services.
- Explicit update checks contact the release service; installation commands may invoke external tooling.
- init-agent itself does not upload repository contents. Connected agents control what tool results they send to their model provider.
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
- optional redacted trajectory sessions and events

It intentionally does not store full file contents.

Metadata is not guaranteed secret-free. Signatures, route names, command
examples, Git messages and user/agent notes can contain sensitive information.
Python signatures omit default expressions, constant values and inline bodies;
this is data minimization, not a general secret detector. Other extractors and
annotations can still retain literals. Rebuild older indexes with `init-agent
map` to replace existing signatures. Old exports, backups and SQLite free pages
are not securely erased by remapping.

Keep `.agent/`, backups and exports private. Do not put credentials or source
snippets in memory notes, feedback or task summaries. Review exports before
sharing them.

## Local Dashboard

`init-agent web` binds only to loopback addresses (`127.0.0.1`, `::1` or
`localhost`), validates Host and Origin headers and disables response caching.
Non-loopback bindings are rejected. It is a read-only local service, not an
authenticated remote dashboard; do not expose it through a public proxy or
tunnel. Other local processes can still access it.

Dashboard memory freshness is checked against current files, not indexed
hashes. Editing a note or its tags does not renew its file evidence: use
`repo_memory_update --revalidate` only after checking the current file.

## Optional Trajectory Hooks

`init-agent trajectory install-codex` installs local Codex lifecycle hooks.
They are disabled by default and separate from MCP. Review and trust the hook
configuration with `/hooks` in Codex before use.

The trajectory collector uses a strict allowlist. It may store event names,
session/turn/tool identifiers, model name, repository-relative paths, tool
executable names, input/output sizes, exit status, duration and subagent
lifecycle metadata. Paths outside the repository are replaced with
`<outside-repository>`.

It does not store prompts, full shell commands, patches, tool output,
subagent messages, chat transcripts or model reasoning. Allowed metadata such
as names and paths can still be sensitive. The collector
is fail-open and silently skips repositories without an existing init-agent
index. Retention is bounded to the latest 5,000 events per repository database.

Hook timestamps measure observable hook intervals and can include harness
overhead. Codex hooks do not expose authoritative model-token accounting or
every internal/hosted operation, so the dashboard must not be interpreted as a
complete model trace.

Unstructured or missing tool results are `unknown`, not successful. The
dashboard reports outcome coverage among completed tool calls and reassesses
older events from their retained evidence without rewriting them.

## Graph Export

`init-agent export --json` exports the indexed metadata graph for external
tools. It includes paths, symbols, relations, Git metadata, feedback and run
summaries, but not full source file contents.

## MCP Server

`init-agent mcp` exposes a compact core set of local metadata contracts over
stdio; `--profile full` retains the complete compatibility surface. It does not
contact external services and does not execute
an LLM. The tools are read-only for project source files and read the existing
SQLite index without auto-mapping or refreshing the repository.

## When Files Are Read

File contents may be read locally during:

- `map`, to extract metadata, symbols and relations
- `refresh`, for changed or new files
- `estimate`, to count characters for token estimates
- memory queries and dashboard snapshots, to check live file hashes

## Generated Files

In most projects, `.agent/` should stay ignored and should not be committed.

You can inspect the local database directly:

```bash
sqlite3 .agent/graph.sqlite ".tables"
sqlite3 .agent/graph.sqlite "select path, language, role from files limit 10;"
```
