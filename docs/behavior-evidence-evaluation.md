# Behavior Evidence Evaluation

This protocol evaluates whether an optional orientation capability helps with
real coding work while preserving answer quality. It is deliberately small; a
positive result is preliminary evidence, not a broad performance guarantee.

## Current status

**Pending.** This document defines a protocol, not a completed comparison. No
same-session baseline-versus-feature measurements are available here, so no
context reduction, quality equivalence or time result is claimed. Existing
experiments may motivate a trial, but they cannot be relabeled as paired data
unless their records satisfy this protocol.

## Protocol

Run at most three paired trials. Each pair uses one independent, previously
unseen task, with the baseline and feature-assisted run performed separately.
Use the same model, model revision, task prompt, repository revision, relevant
context, tool permissions and time limit within each pair. Avoid sharing notes,
patches, discoveries or outputs between the two runs. Randomize which arm runs
first when practical. Record deviations rather than silently treating them as
equivalent.

Choose tasks that require finding and understanding behavior, and define the
expected behavior and acceptable solution before either run. Keep the task
prompt identical within the pair. Do not use repeated prompts on one underlying
bug as though they were independent tasks.

For each run, record:

- task identifier and repository revision;
- model name and exact revision, plus context and tool settings;
- baseline or feature arm and whether the feature operated successfully;
- input context tokens and total model context tokens consumed, using the same
  accounting method for both arms;
- elapsed wall-clock time from task start through final answer;
- whether the result met the prewritten correctness criteria, with supporting
  tests or source evidence;
- material omissions, false paths, unsupported claims, failed checks and
  human interventions.

Quality review should use identical criteria for both arms. At minimum, check
correctness of the requested behavior, whether cited paths really support the
claims, whether important gaps were disclosed, and whether required checks
passed. A cheaper or faster incorrect result is not a quality-preserving win.

## Decision threshold

The feature is eligible for a limited release recommendation only if all of
these conditions hold:

1. At least two of the three independent pairs are completed with valid,
   comparable measurements.
2. Feature-assisted runs reduce total context tokens by at least 20% in at
   least two of the three pairs, comparing within each pair.
3. No feature-assisted result has worse task quality than its paired baseline.
4. Elapsed time shows no systematic rise across the pairs. Report each pair's
   time; with only two or three pairs, do not hide mixed or noisy results behind
   an average.
5. The feature's own output has no unresolved correctness issue that could
   materially mislead an agent, including false resolved links or stale
   evidence presented as current.

If fewer than three pairs are available, report the sample size and treat the
result as preliminary. A failed or invalid pair is not a success and must be
explained. If any threshold is not met, leave the release decision pending or
record the result as not met; do not change the threshold after seeing results.

## Reporting template

| Pair | Task | Revision/model matched? | Context tokens baseline → feature | Quality baseline → feature | Time baseline → feature | Valid? |
|---|---|---|---:|---|---:|---|
| 1 | Pending | Pending | Pending | Pending | Pending | Pending |
| 2 | Pending | Pending | Pending | Pending | Pending | Pending |
| 3 | Pending | Pending | Pending | Pending | Pending | Pending |

Record the task prompts or stable task identifiers, rubric, raw measurements,
deviations and evidence links with the results. Preserve both runs so another
reviewer can inspect what each arm saw and produced. Until actual paired data
is collected and reviewed, the status remains **pending** and optional features
remain experimental; do not promote them in release guidance.

## Implementation verification — 2026-10-17

The implementation is delivered behind the optional evidence switch. The known
init-agent integration snapshot indexed 215 files with zero extraction errors;
a trace anchored at `init_agent/refresh.py:refresh_index` returned ten paths and
explicit result-limit/unresolved gaps. All returned endpoint line numbers were
checked against snapshot files. The 1.461-second local preparation/trace run is
an integration observation, not an estimate of agent time savings.

The optional TypeScript 5.8.3 compiler was installed explicitly for tests; its
lockfile has integrity data. Real PHP tree-sitter 0.25.2 / tree-sitter-php 0.24.1
was tested in a disposable venv. This macOS host cannot enforce the isolated
native worker limits, so production PHP indexing correctly falls back; real
parser integration tests invoke the actual parser at a controlled test seam.
A FlowPilot checkout was not identified in the supplied workspace, so that
integration remains unverified.

The user had no current novel problem list and requested a security review.
That review confirmed and fixed one low-severity local refresh failure; see
[the security report](../security_best_practices_report.md). It did not establish
a paired utility comparison. No token/context reduction or promotion threshold
is claimed. Further analyzer expansion and default promotion remain gated on
independent comparisons, with no paid model API used for this work.
