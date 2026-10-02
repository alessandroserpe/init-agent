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
Code signatures are reconstructed from declaration names and conservative
parameter/type shapes, omitting literal defaults and bodies. All signatures
are capped at 256 UTF-8 bytes at extraction, persistence and graph export,
including export from older databases. This is data minimization, not a general
secret detector: names, routes, documentation commands and package scripts can
still contain sensitive information. Index version 11 requires `init-agent map`
to replace previously stored signatures. Old exports, backups and SQLite free pages
are not securely erased by remapping.

Keep `.agent/`, backups and exports private. Do not put credentials or source
snippets in memory notes, feedback or task summaries. Review exports before
sharing them.

On Unix, init-agent creates and reopens `.agent` with mode 0700 and its regular
metadata files with mode 0600, independently of the process umask. SQLite is
pre-created at 0600 so journals/WAL sidecars inherit that mode. Configuration
writes, configuration backups and MCP debug logs also use owner-only files.
Unsafe symlinks, hard-linked files, unexpected file types and ownership are
rejected before changing or truncating a file; permission-setting failures are
reported rather than silently ignored. Existing permissive Unix modes are
hardened on access. This does not revoke copies already obtained by other users.

macOS extended ACLs can grant access beyond Unix mode bits; init-agent warns
when one is present so the operator can review it. On Windows, native ACLs
remain the operator's responsibility. Exports are written to stdout: when
redirecting them to a file, use a private destination, for example
`(umask 077; init-agent export --json > graph-export.json)` for a new file.

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
- `trace`, to match query terms against indexed files
- memory queries and dashboard snapshots, to check live file hashes

## Untrusted Repository Metadata

`trace` and `estimate` validate indexed paths before reading files. Absolute
paths, parent traversal, missing files and symlinks that resolve outside the
repository are skipped. Metadata access rejects a symlinked `.agent` directory
or symlinked files directly inside it, including SQLite sidecars. Use a real
local `.agent` directory for each repository.

Generated commands quote repository-derived arguments for POSIX shells,
including dollar signs and backticks. Human-readable CLI output and text
renderers escape terminal control sequences; JSON retains the original values
through JSON escaping.

Trace traversal shares a budget of 1,000 states across all starts and caps its
queue at 1,000 paths. Trace and estimate share bounded, cached reads within each
request: at most 256 files, 256 KiB per file and 8 MiB total, with a five-second
elapsed-time check between operations. Trace also bounds index rows and graph
edges before traversal. Responses flag partial results when limits are reached;
partial estimate counts and savings do not describe the complete repository.
Automatic preparation/mapping is separate from these analysis budgets.

Mapping applies per-file parser limits before processing recursive inputs:
2 MB input, nesting depth 64, 100,000 tokens/delimiters, 50,000 visited nodes
and 10,000 emitted symbol/relation records. Python logical statements are
also limited to 512 tokens. Cooperative elapsed-time checks use a two-second
budget. These checks do not forcibly interrupt native parser calls; process
isolation is needed for a hard CPU/memory sandbox.

Parser resource failures skip the affected file, remove any stale symbols
for it, record a bounded diagnostic and continue mapping other files. Map
summaries retain the failure count and up to 50 diagnostics. PHP tree-sitter
extraction splits source lines once per file and checks its node traversal.

Git metadata reads disable filesystem monitors, hooks, external diffs and
text conversion, avoid system/global configuration and lazy object fetching,
and time out each subprocess after ten seconds. Prepared working trees with
local Git configuration are treated as untrusted for these execution features.
Git itself remains a required, trusted local installation.

MCP installation discovers executables in known runtime and installation
directories rather than searching the ambient `PATH`. Automatic discovery
rejects executables in the target repository, unsafe ownership and group/world
writable paths. An explicit `--codex-command` must be an absolute executable
path outside the repository; supplying it selects that binary as trusted.
If Codex is installed elsewhere, use this option.
Use `--server-command /absolute/path/to/init-agent-mcp` to explicitly select
the server executable under the same rules, including in shared runtime
installations rejected by automatic discovery.
The resolved absolute server command is persisted and reported in installation
results.

Reading-plan manifest decoding accepts at most 8 MiB of compressed input and
8 MiB of decompressed JSON. Oversized, malformed or truncated manifests are
ignored, disabling automatic inference of newly created files for that plan.

The deterministic evaluator (`experiments/evaluate.py`) starts child Python
processes with `-I -S` and explicitly loads the evaluator's checkout. The
measured repository, `PYTHONPATH`, startup hooks and site packages cannot
provide Python startup code to those children. This startup isolation is not
an operating-system sandbox for executing repository code.

## Generated Files

In most projects, `.agent/` should stay ignored and should not be committed.

You can inspect the local database directly:

```bash
sqlite3 .agent/graph.sqlite ".tables"
sqlite3 .agent/graph.sqlite "select path, language, role from files limit 10;"
```
