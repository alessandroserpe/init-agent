# init-agent Skill

This directory contains the public source of the optional
`init-agent-orientation` skill. The skill teaches a coding agent when to use the
local init-agent map and how to keep the workflow bounded.

The CLI and MCP server work without the skill. The packaged copy used by
`init-agent install-skill codex` lives under `init_agent/resources/skills/` and
is kept identical by tests.

## Install For Codex

After installing init-agent:

```bash
init-agent install-skill codex
init-agent mcp install-codex
```

After a package upgrade, synchronize the installed skill and inspect the MCP
registration:

```bash
init-agent sync
```

Backups are stored outside Codex's skill discovery directory under
`~/.codex/init-agent-backups/skills/`.

From a source checkout, manual installation is also possible:

```bash
mkdir -p ~/.codex/skills
cp -R skills/init-agent-orientation ~/.codex/skills/
```

Restart Codex after installation or synchronization.

## Workflow Taught By The Skill

The default loop is intentionally small:

1. Use `repo_overview` when broad orientation is needed.
2. Create one bounded `repo_reading_plan` for the task.
3. Read and verify the suggested files directly.
4. Use `repo_related_file` or `repo_symbol_callers` only for a concrete
   follow-up.
5. Finish once with `repo_reading_plan_finish`, including the ordered files read
   and verified outcomes.
6. Store memory only for stable facts worth reusing.
7. Use `repo_session_close` before handoff.

The default MCP `core` profile exposes this loop. Administrative, diagnostic,
scorecard, task and legacy ledger tools remain available through the CLI or the
explicit MCP `full` profile, but the skill does not call them merely because
they exist.

## Other Coding Agents

Only the Codex installation path is automated because it has been verified.
Other agents can use the Markdown workflow without a native skill installer:

```bash
init-agent run --overview --markdown
init-agent plan "<task>" --read 3
# verify files directly
init-agent plan finish --id <id> --read-file <path> --verified <path> --central <path> --summary "Verified outcome."
init-agent session close
```

Do not add a client-specific installer until that client's instruction format,
installation path and reload behavior have been tested.

## Local Development

For an editable installation:

```bash
python3 -m pip install -e /path/to/init-agent
init-agent --version
```

Without installing the package, commands can run from the checkout with:

```bash
PYTHONPATH=/path/to/init-agent python3 -m init_agent.cli --version
```

If `init-agent` is not found, check the active installation and `PATH`:

```bash
which init-agent
python3 -m init_agent.cli --version
```

The skill provides orientation, not authority. Agents must still read the real
files before editing and verify changes with the repository's tests.
