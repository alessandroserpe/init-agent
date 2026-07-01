# Roadmap Notes

This document tracks near-term product work that should make init-agent easier
to explain, evaluate and use in real agent sessions.

## Priority Backlog

### 1. Repeatable Demo

Build one clear end-to-end demo on a medium or large repository.

The demo should compare a normal agent run with an init-agent-assisted run on
the same task. Track simple, visible metrics:

- files opened before the useful file was found
- exploratory commands run
- estimated elapsed time from logs
- whether the targeted test passed
- whether feedback or memory improved the next similar run

Success means the project can show one concrete story instead of only a feature
list.

### 2. Credible Benchmark Set

Expand the current experiments into a small benchmark suite with real tasks and
repositories.

Suggested first metrics:

- top-1 and top-3 useful-file hit rate
- files read before fix or answer
- exploratory command count
- test result
- ranking improvement after feedback

Keep the benchmark small enough to run locally and explain in a README.

### 3. Shorter Happy Path

The current workflow is powerful but requires several explicit commands:
`plan`, `plan read`, `plan diff`, `plan finish`, feedback and memory.

Explore a higher-level command such as:

```bash
init-agent work "fix login bug" --read 3
```

The command should guide the user or agent through the recommended next step
without hiding the underlying plan, read tracking and finish semantics.

### 4. More Invisible Agent Integration

Make MCP and bundled skills use reading plans naturally:

- create a plan at the beginning of broad work
- record files that were actually opened
- close the plan with useful, noisy or missing outcomes
- suggest memory only when stable facts were verified
- surface unfinished plans during session close

Success means the user does not need to micromanage the orientation loop.

### 5. Lightweight Visualization

Add a simple visual output before building a full UI.

Possible shape:

```bash
init-agent graph --html
```

The first version can be a static HTML report showing trace paths, suggested
files, local memory, feedback and topic/flow groups.

### 6. Ranking Improvement Story

Demonstrate that feedback and memory improve later orientation.

The important claim to validate is:

> init-agent gets better as agents verify work.

Track whether repeated or similar tasks move verified useful files earlier and
push noisy files down.

### 7. Focused Language And Framework Depth

Prefer depth over broad shallow support.

Initial focus areas:

- Python
- JavaScript/TypeScript
- PHP legacy projects

Improve entrypoint detection, relation extraction and noisy-file filtering in
these ecosystems before expanding broadly.

## Positioning

init-agent should not claim to invent codebase context or agent memory. The
stronger, more accurate positioning is:

> init-agent makes repository orientation local, agent-agnostic, inspectable
> and improvable through verified feedback.

