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
Non-loopback bindings are rejected. Loopback is a routing boundary, not user
authentication: each launch generates a 256-bit random bearer capability and
requires it before reading or returning repository metadata. Open the private
link printed in the terminal. Its fragment is removed from the address bar and
the browser retains the capability in tab-scoped session storage, sending it
only in the Authorization header. The unauthenticated landing page contains no
repository metadata or capability. Restarting the server invalidates old links.
Treat the launch link and terminal output as private; do not expose the service
through a public proxy or tunnel. Processes able to read the owner's terminal,
browser storage or process memory remain outside this protection.

The HTTP service admits at most four active connections and twenty new
connections per second, with a five-second connection deadline and socket
timeout. Request lines are limited to 4 KiB and headers to 16 KiB. Authenticated
requests share one snapshot build and a two-second cache, including failed
builds. SQLite work has a 500,000 VM-step/two-second cooperative budget and a
64 KiB row/string limit. Table counts stop at 10,000 and are labeled as lower
bounds when they reach that cap. Activity and trajectory aggregates use windows of
1,000 records; scorecard details are restricted to selected plans and 1,000
records. These windows are reported in the dashboard. Live freshness hashes
read at most 256 KiB per file and 8 MiB per snapshot; skipped checks report
unknown freshness. JSON and HTML responses are limited to 2 MiB. Exhausted
snapshot budgets return a bounded 503 response. Slow filesystem operations
are not forcibly interrupted; this service is not a process-level sandbox.

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

Ignore configuration is read only from a regular file, with a 64 KiB byte
ceiling and a nesting preflight before JSON decoding. It must be an object;
collections contain at most 256 entries and strings at most 1,024 characters.
Ignore fields must be lists of strings. Invalid configuration falls back
atomically to default ignore rules without retaining partially validated rules.

The explicit evaluator in `experiments/evaluate.py` gives each init/map/git
or case subprocess a 120-second deadline and a combined stdout/stderr limit
of 1 MiB. Capture is incremental through a bounded queue. On POSIX the parent
terminates the process group, including descendants retaining output pipes;
Windows uses tree termination with a direct-child kill fallback. Failures,
including rebuild failures, become case results with at most 2,048 characters
of diagnostics. This is a work budget, not containment of malicious code that
deliberately escapes its process group.

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

Repository operations additionally share one aggregate budget across nested
preparation, Git, mapping, refresh, relation/term rebuilding, context, overview
and index-health work. CLI commands and MCP tool calls use a 30-second
cooperative deadline, 10,000 visited filesystem entries, 200,000 fetched rows,
200,000 database/generated records, 128 MiB of cumulative metadata accounting
(including a per-record allowance), 64 MiB of file reads/hashes, one million
Python work checkpoints and ten million SQLite VM instructions. SQLite values
are capped at 8 MiB and metadata strings at 16,384 characters. Paths are capped
at 4,096 characters and 64 components. These are work limits, not a hard limit
on process RSS or a forced interruption of blocking filesystem/native calls.

Exhaustion stops the operation with an explicit incomplete-result diagnostic;
CLI/MCP JSON reports `status: error` and `truncated: true`. Uncommitted rebuild
changes are rolled back; previously completed preparation phases can remain
committed. Narrow the repository scope before retrying an interrupted map.
Rows are fetched incrementally, generated relation inserts stream through the
budgeted cursor, and term statistics retain counters instead of duplicate
document corpora. The dashboard retains its separate request budgets.

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

Git is selected as an absolute executable from known installation directories,
never from ambient PATH. Git children receive a restricted system-tool PATH.
Output capture is incremental and limited to 2 MiB per Git subprocess and
8 MiB across the repository operation, with process-group termination on
POSIX if the output or deadline budget is exceeded.

The same executable resolver is used for MCP installation and trajectory
hooks. On POSIX, automatic tools and all hook overrides require a root- or
current-user-owned path chain with no group/world-writable component, outside
the target/current repository. Hook overrides must be absolute executable
paths. Hook configuration persists the resolved absolute path; legacy bare
commands are marked non-current and replaced by the next explicit install.
Unusual installations may require moving the executable into a private,
trusted installation directory. No hook installation is performed implicitly.

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

### Repository reads and rendered metadata

Live repository reads use component-wise directory-descriptor opens with
`O_NOFOLLOW`, reject non-regular files, and never reopen a checked pathname to
obtain content. Mapping and refresh derive text, hash, size and modification time
from the same open descriptor; an in-place change detected during reading is
reported as a per-file error. Symlinks inside the selected root (including those
pointing inside it) are skipped. Platforms without `dir_fd`/`O_NOFOLLOW` fail
closed for live reads rather than using a pathname-check fallback. The selected
repository root itself is trusted. Hashing has a 64 MiB per-file ceiling in
addition to request-wide budgets.

Overview and context Markdown encode each repository-derived value as literal
inline data, with backtick delimiters longer than any embedded run and visible
newline/tab escapes. Rendered metadata remains untrusted evidence, even when its
Markdown structure is safe.

### Persistent metadata quotas

MCP handlers and public metadata mutation functions reject collections over 128
items, strings over 4,096 characters, nesting over eight levels, and input over
64 KiB before mutation. MCP schemas advertise string and collection limits.
SQLite additionally enforces a shared 64 MiB logical payload quota for notes,
tasks, feedback and reading plans. Records are limited to 32 KiB (512 KiB for a
plan including its compressed file manifest). Row ceilings are 1,000 notes,
tasks, plans and workstreams per table, 5,000 feedback and task-note rows per
table, and 10,000 plan items and events per table. These are metadata limits;
they do not describe SQLite's physical file size or the source graph tables.

Quota failures roll back the active mutation and ask the operator to export or
remove old metadata. Existing user records are not automatically deleted.
Plan finalization commits events, feedback and completion atomically; repeating
finalization returns `already_finished` without adding records. Classification
changes require a new plan; the separate kind-marking operation remains available.

Feedback reads default to the latest 1,000 rows and support `limit` (up to 5,000)
and `before_id` pagination in the Python API. Feedback export returns a bounded
page, with `truncated` and `next_before_id` for legacy histories above 5,000 rows.
Task details return the latest 100 notes and `notes_truncated`. Plan details cap
items/events and expose `history_truncated`; scorecards load only the selected
recent finished plans and bounded matching histories before calculating results.

### Metadata directory lifetime and SQLite namespace

Configuration, export and log files directly inside `.agent` are opened relative
to a retained `O_DIRECTORY|O_NOFOLLOW` directory descriptor. The direct-child
namespace allows only owner-owned, single-link regular files: SQLite's main
file and fixed journal/WAL/SHM names, configuration, and optional regular
backups/exports/logs. Directories, FIFOs, sockets, devices and symlinks are
rejected before SQLite is called; validation also caps children at 256.

The standard Python SQLite binding cannot accept a directory descriptor.
Connections therefore keep both the validated directory and database handles
alive, use `mode=rw` (no pathname-based creation) or `mode=ro`, and verify their
identities at handoff and before statements/commits. **SQLite metadata access is
unsupported in a namespace writable by another OS user.** Every resolved
ancestor must be owned by the current user or root and lack group/other write
permission; a root-owned sticky temporary ancestor is allowed when its child is
owned by the current user/root. Write-granting macOS ACLs are rejected too.
This prevents another local principal from replacing `.agent` or its ancestors
while SQLite uses pathnames for the database and sidecars. No repository
permissions are changed to bypass this requirement; use a private checkout.

These controls are not a sandbox against root or malicious processes running
under the owner's own UID, which can already access private metadata. Detected
same-UID directory/database replacement fails closed, but identity checks alone
are not claimed to eliminate every same-UID rename race. POSIX descriptor and
ownership support is required; there is no insecure fallback on other platforms.

### Optional manual-scan benchmark

The evaluator treats indexed paths as untrusted. Manual-scan measurement uses
the same descriptor-anchored repository reader, rejects absolute/traversal
paths, symlinks and non-regular files, and skips targets above 256 KiB. A
measurement is limited to 256 rows/files, 8 MiB of file bytes, five seconds of
cooperative work and 500,000 SQLite VM steps. Database paths are opened through
the metadata connection guard in read-only mode. Results expose rejected-file
counts and `truncated`; partial measurements must not be interpreted as complete
repository read costs.

### MCP transport limits

Transport limits apply before repository/tool budgets: JSONL lines and declared
Content-Length bodies are capped at 256 KiB. Header lines are capped at 4 KiB,
with at most 32 headers and 16 KiB of header bytes. The first line has the frame
ceiling before its framing type is known. More than 16 leading empty lines,
duplicate/invalid Content-Length values, truncated bodies and non-object JSON
are fatal framing errors. A pre-decode scan caps JSON nesting at 32 and structural
tokens at 8,192. Method/tool names are at most 128 characters and string request
IDs at most 256. On a framing error the process exits with status 1; it does not
allocate/drain the advertised body or dispatch a trailing frame. Local stdio
remains a blocking transport controlled by its connected client, not a network
service with per-client read deadlines.

### Git administrative boundary

Git commands receive validated explicit `--git-dir` and `--work-tree` paths.
A `.git` symlink or special file is rejected. A gitdir file must name a real
relative directory inside the selected root, without parent traversal. The
administrative tree must contain only real directories and regular files; the
validation walk is capped at 20,000 entries per repository operation. Linked
worktrees (`commondir`) and object alternates are unsupported, even when they
would be internal: use a self-contained clone for indexing. Rejected Git layouts
fall back to non-Git source enumeration and contribute no Git history. Inherited
`GIT_*` variables are removed before installing the controlled read environment,
so ambient gitdir/object-store/config overrides cannot bypass this boundary.

### Dashboard browser origin and CI dependencies

`init-agent web` now defaults to port 0: the OS selects an available ephemeral
port, and the launch output prints that exact origin and capability URL.
`--port N` explicitly opts into a reusable origin and weaker browser-state
isolation. Random port selection reduces predictable origin reuse; it does not
guarantee a never-before-used browser origin. For stronger same-host threats,
use an isolated browser profile. Existing capability and routing checks remain.

CI actions are pinned to full upstream commit SHAs, with their release versions
in comments. The workflow declares `contents: read` and checkout does not retain
Git credentials. Updating action versions requires a reviewed SHA change.

### Native PHP parser isolation and Git configuration policy

Optional PHP tree-sitter never parses source in the mapper process. A disposable
Python worker starts with isolated startup (`-I -S`) and explicit trusted package
paths. Before reading input or loading tree-sitter, it installs a 512 MiB hard
address-space ceiling, a two-second CPU limit and disables core dumps. The parent
independently limits wall time to two seconds, input to 2 MB and output to 4 MiB,
and kills the worker process group on exhaustion. Native tree construction is
bounded by OS memory/CPU limits; the tree walk still enforces node/record limits.
The lexical preflight now counts identifier/number runs, string literals,
operators and invalid characters rather than delimiters alone. It is a
conservative preflight, not a replacement for native process isolation.

If optional packages or enforceable OS limits are unavailable, extraction uses
the bounded regex fallback. In particular, platforms rejecting `RLIMIT_AS` do
not run the native parser. A worker timeout, crash or resource exhaustion is a
per-file parse failure; it does not retry native parsing or stop other files
from being mapped. Linux CI additionally installs the optional packages and
checks real native extraction, address-space enforcement and timeout cleanup.

Git's repository-local config is now parsed without invoking Git and accepted
only through a small allowlist of non-executing keys in core, user, remote,
branch, init and extensions sections. Filter/diff/merge drivers, aliases,
credential helpers, pagers, hooks, fsmonitor, includes, worktree configs and
unknown keys/sections are rejected. Escapes, continuations and control-character
syntax are also rejected to avoid parser differences. The validated namespace
and config must not be writable by other OS users. Existing command-line
suppression remains defense in depth. Unsupported configurations disable Git
metadata collection and use ordinary source-file enumeration; configuration
files are never rewritten by this policy.
