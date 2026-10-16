# Orientation prompt compaction

The standalone and bundled `init-agent-orientation/SKILL.md` copies now contain
the same concise, self-contained workflow. Detailed maintenance instructions
remain in the existing CLI/tool help and project documentation instead of being
repeated in every skill invocation. No extra reference files or package changes
are needed.

The skill preserves bounded orientation, index freshness, targeted recovery,
verified plan completion and scoring feedback, durable memory, session handoff,
privacy and opt-in telemetry/delegation. It explicitly reuses an already supplied
current plan rather than asking for it again. No tool, task API or scoring
implementation was removed.

## Measurement

Each of the 15 archived assisted prompts from pilot 004 was reconstructed with
only the old skill text replaced by the new skill. Original task descriptions,
initial-plan errors and adapter instructions were kept byte-for-byte identical.
The archived originals were not modified.

| UTF-8 bytes | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Skill file | 7,667 | 3,331 | 56.6% |
| Median initial prompt across 15 runs | 8,562 | 4,226 | 50.6% |

This isolates the effect of skill compression. It is not a new model benchmark,
a token count or a measured cost/latency improvement. It excludes tool schemas
and provider/system instructions. A successful initial plan can be longer than
the failed plans in the original pilot, so 4,226 bytes is not a size limit or
a forecast for every future prompt. The previous preparation fix and this skill
change must be evaluated together in a new series to measure end-to-end impact.

Both benchmark adapters read the bundled skill at execution time, so new runs
use the shorter version. Existing completed series stay frozen. A globally
installed skill requires `init-agent sync` to receive the repository's updated
bundle; this change does not rewrite an existing conversation's context.

## Checks

- 28 documentation/installation tests passed, including source/bundle equality
  and install/sync behavior.
- YAML frontmatter validated with Ruby's safe YAML parser.
- The skill-creator Python validator could not start because its interpreter
  lacks PyYAML; no dependency was installed solely for this check. The simple
  two-field frontmatter and body were also inspected directly.
- `git diff --check` passed. Behavioral equivalence and actual model savings
  require a new agent evaluation; text reduction alone does not establish them.

Per-prompt byte measurements are retained privately at
`results/prompt-compaction-20261016/comparison.json`.
