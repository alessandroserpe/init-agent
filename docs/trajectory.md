# Observable Trajectory

The optional trajectory feature records a local, technical timeline of
observable Codex activity. It helps a developer answer questions such as:

- which tools were used and in what order;
- which repository files appeared in tool inputs;
- how long paired tool calls took;
- which calls succeeded or failed;
- when subagents started and stopped.

It is not the chat transcript and it is not model chain-of-thought.

## Enable It

Install the lifecycle hooks once:

```bash
init-agent trajectory install-codex
```

Then open `/hooks` in Codex, review and trust the configuration, and restart
Codex. Check the local status with:

```bash
init-agent trajectory status
init-agent sync
```

The installer preserves unrelated hooks and creates a timestamped backup when
it changes an existing `hooks.json`. Remove only init-agent handlers with:

```bash
init-agent trajectory uninstall-codex
```

## What Happens During Work

Supported Codex lifecycle events invoke the lightweight `init-agent-hook`
executable. The collector finds the nearest parent repository with an existing
`.agent/graph.sqlite` and writes bounded metadata there. It never initializes
or maps a repository from a hook.

The initial event set is intentionally small:

- `SessionStart` and `SessionEnd`;
- `PreToolUse` and `PostToolUse`;
- `SubagentStart` and `SubagentStop`;
- `Stop`.

The hook exits successfully on malformed input, missing indexes, lock errors or
other collection failures so observability cannot block coding work.

## Stored Metadata

The allowlist includes event/session identifiers, model name, event status,
tool name, repository-relative paths, executable name, payload sizes, exit
status, paired-tool duration and subagent lifecycle identifiers. Duplicate
events are ignored and retention is bounded to the latest 5,000 events per
repository.

The collector does not store:

- user prompts or chat messages;
- full commands or environment values;
- patches or source snippets;
- tool output;
- subagent responses;
- secrets or paths outside the repository;
- hidden model reasoning.

Inspect the timeline with:

```bash
init-agent web
```

The dashboard remains read-only. `/api/snapshot` and `--snapshot-json` expose
the same bounded metadata for inspection.

## Limits

This is an observable event timeline, not a complete execution trace. Hook
durations may include harness overhead. Codex hooks do not currently provide
authoritative token counts and may not expose every hosted or internal
operation. The data is useful for debugging workflow and navigation behavior,
but it should not support claims about full model reasoning or exact billing.
