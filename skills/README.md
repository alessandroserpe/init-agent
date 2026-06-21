# init-agent Skills

This directory contains optional agent-facing skill templates.

They are not required for the `init-agent` CLI. They are small instruction files
that tell coding agents how to use `init-agent` as an orientation tool before
reading a repository broadly.

## Available Skills

- `init-agent-orientation`: run `init-agent run --overview` for broad repo
  orientation, run `init-agent run "<task>"` for task-specific context, then
  use `symbol`, `callers`, `related`, `estimate` and `doctor` for targeted
  follow-up.

## Install For Codex

From this repository:

```bash
mkdir -p ~/.codex/skills
cp -R skills/init-agent-orientation ~/.codex/skills/
```

Open a new Codex session and ask:

```text
Usa la skill init-agent-orientation per orientarti in questo repository.
```

## Local CLI Shim

If `init-agent` is installed in editable mode, the normal command should work:

```bash
python3 -m pip install -e /path/to/init-agent
init-agent --version
```

For local development without installing a package, create a small shim.
Replace `/path/to/init-agent` with your checkout path:

```bash
mkdir -p ~/.local/bin
printf '%s\n' '#!/usr/bin/env bash' \
  'exec env PYTHONPATH="/path/to/init-agent" python3 -m init_agent.cli "$@"' \
  > ~/.local/bin/init-agent
chmod +x ~/.local/bin/init-agent
```

Make sure `~/.local/bin` is in your `PATH`:

```bash
echo "$PATH"
which init-agent
init-agent --version
```

If needed, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Troubleshooting

### `init-agent: command not found`

The command is not in `PATH`.

Check:

```bash
which init-agent
python3 -m init_agent.cli --version
```

If `python3 -m init_agent.cli --version` works from the `init-agent` checkout,
install the package or create the shim above.

### `Argument expected for the -m option`

The shim is broken, usually because the command was split across lines or the
redirection wrote to the wrong path.

Recreate it with the `printf` command above. Avoid manually wrapping this line:

```bash
exec env PYTHONPATH="/path/to/init-agent" python3 -m init_agent.cli "$@"
```

### The skill runs but ranking is noisy

Run a more specific follow-up instead of only rephrasing the same question:

```bash
init-agent symbol "<symbol>"
init-agent callers "<symbol>"
init-agent related path/to/file
```

The context pack is an orientation layer. The agent should still read the files
it plans to rely on.

## Copy-Paste Workflow For Other Agents

Use this short instruction with Codex, Claude Code, Aider, OpenCode or similar
CLI agents:

```text
Before broad repository inspection, run:
init-agent run --overview --markdown

For a specific task, run:
init-agent run "<my task>" --markdown

Use the suggested first reads as candidates, then verify by reading files.
If the task mentions a function/class/symbol, also run:
init-agent symbol "<name>"
init-agent callers "<name>"

If a likely file is found, run:
init-agent related path/to/file

Do not treat init-agent output as source of truth. It is a local orientation
map, not an LLM and not a semantic analyzer.
```
