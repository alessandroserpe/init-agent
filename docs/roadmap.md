# Roadmap

This page tracks product directions that should make `init-agent` easier to
explain, evaluate and use in real agent sessions.

The roadmap is intentionally conservative: features should reduce orientation
work or make agent behavior easier to inspect. Avoid adding commands only
because they are possible.

## Near-Term Priorities

### 1. Validate The Compact Agent Loop

Observe whether fresh agents can complete normal work with the default MCP
core profile:

```bash
init-agent overview
init-agent plan "<task>" --read 3
init-agent plan finish --id <id> --read-file <path> ...
init-agent session close
```

Only promote a full-profile tool back into the core when repeated real tasks
show that the smaller loop cannot express the required workflow.

### 2. Longitudinal Orientation Evidence

Keep improving small, repeatable experiments that measure orientation quality:

- whether useful files appear in the top 1, 3 or 5 suggestions;
- how often important files were missing from the initial plan;
- how much noise appears in planned reads;
- how many files the agent reads before finding a useful one.

These metrics should stay separate from broad claims about agent speed or patch
quality.

### 3. More Useful Dashboard

Keep the dashboard read-only, but improve how it explains local agent behavior:

- recent useful and noisy files;
- scorecard trends over time;
- stale memory needing review;
- recurring topics, tags and flow groups;
- optional lightweight graph views.

The dashboard now also supports an optional redacted trajectory timeline for
observable Codex lifecycle events. Future work should validate whether those
events improve human understanding before expanding capture depth.

The dashboard should help humans understand what the agent did without turning
into a project management system.

### 4. Ranking, Memory And Feedback Quality

Validate that feedback, memory and tags make later orientation better:

- useful files should move earlier for similar tasks;
- noisy files should move down;
- missing files should become visible in future plans;
- stale or low-quality notes should be easy to audit.

The scorecard should stay honest about weak areas instead of hiding them.

### 5. Focused Language And Framework Depth

Prefer depth over broad shallow support.

Current focus areas:

- Python;
- JavaScript and TypeScript;
- PHP legacy projects.

Improve entrypoint detection, relation extraction and noisy-file filtering in
these ecosystems before expanding broadly.

The graph already stores qualified Python/PHP symbols, callable scope, resolved
symbol calls and inheritance edges. Before adding more relation types or
languages, validate precision, index size and ranking impact on real projects.

## Longer-Term Ideas

- Dependency-aware incremental refresh.
- More agent-install helpers after each client format is verified.
- Broader optional tree-sitter support where it provides clear value.
- Structured experiment archives for paired agent runs.
- Optional bounded graph views inside the existing read-only dashboard.

## Positioning

`init-agent` should not claim to invent codebase context or agent memory. The
stronger, more accurate positioning is:

> init-agent makes repository orientation local, agent-agnostic, inspectable
> and improvable through verified feedback.
