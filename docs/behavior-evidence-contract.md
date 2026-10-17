# Behavior And Evidence Contract

`init-agent` is an orientation and evidence aid. Its output is a set of leads
for an agent to inspect; it is not proof that a runtime behavior is complete,
current or correct. Before changing code, an agent must read the cited source
and verify the behavior in context.

Every useful answer about a behavior should make five things clear:

1. **Where can it start?** Identify likely application entry points and state
   how they were found. Entry-point discovery is heuristic and may miss
   framework-specific or custom boot files.
2. **What path connects the start to the behavior?** Give repository-relative
   paths and, when available, relation types or source line ranges. A resolved
   relation means the index found an unambiguous target under its resolver; it
   does not prove that runtime execution follows that path. Never present an
   unresolved guess as a resolved link. When a relation has no unique target,
   label it unresolved or omit the link and ask the agent to inspect the
   source.
3. **What is known, and what is missing?** Separate indexed evidence from
   inference. Call out missing entry points, unresolved relations, unsupported
   language/framework patterns, truncated results and files that need direct
   inspection. Do not turn an empty result into a claim that a path does not
   exist.
4. **Can prior context be reused, and is it fresh?** Reuse local notes and
   feedback only with their scope and freshness status visible. File-scoped
   notes may be stale or lack hash evidence; repo-scoped notes have no
   file-level freshness claim. Index freshness warnings matter: refresh or map
   before relying on graph-sensitive conclusions when the index reports
   changes. Freshness checks do not establish semantic correctness.
5. **What evidence verifies the conclusion?** Distinguish source inspection,
   tests actually run, and stored historical test records. A test candidate is
   only a candidate; a saved verification is scoped to its recorded files and
   time. State when no verification was run, and do not imply that a check
   passed merely because a command or candidate was suggested.

## Capability inventory

This inventory describes implemented product surfaces and their limits. The
status labels describe availability, not proven usefulness on every project.

| Status | Capability | Evidence and limits |
|---|---|---|
| Available | Repository overview and likely entry points | `overview` and `repo_entrypoints` return heuristic candidates; custom boot files can be missed. |
| Available | Task-specific plans, graph trace, related files and symbol callers | These return ranked or resolved metadata from the local index. Dynamic dispatch, reflection, dependency injection and ambiguous targets can remain unresolved. |
| Available | Local memory and feedback | Notes can be searched and audited; file-scoped note freshness is checked against file hashes. Feedback records an agent's stated outcome and is not independent validation. |
| Available | Reading-plan outcome records | Agents can record files read, verified, useful, noisy or missing. The records depend on accurate agent reporting and do not observe editor activity automatically. |
| Available | Index health and incremental refresh | Health checks report path-level changes; `refresh` updates changed files. Refresh rebuilds dependent resolved relations, invalidates changed analyzer fingerprints and checks TypeScript source/configuration dependencies. Health checks do not certify extracted relations. |
| Available | Optional test candidate lookup and saved task checks | Candidate lookup reports source-level call/assertion evidence but does not run tests. Optional task checks run a selected unittest and record scoped file-version evidence. |
| Available | Optional redacted trajectory and read-only dashboard | Trajectory capture requires separate setup and records bounded lifecycle metadata. It does not capture prompts, full commands, patches or model reasoning. |
| Experimental | `repo_search` source-passage search as the full-text MCP entry point | It includes line evidence and freshness warnings and can initialize or refresh its local index during a search call. Its behavior and utility still require evaluation on representative tasks; see [MCP integration](mcp.md). Treat ranking as a lead and inspect the source. |
| Experimental | Optional orchestration/delegation advice and other prototype experiments | Advice does not launch agents or select provider-specific models. Experiment results are local evidence and must not be generalized beyond their task and setup. |
| Missing | Guaranteed complete runtime paths across frameworks and languages | Discovery and parsing are heuristic; dynamic and framework-specific behavior can be absent or ambiguous. |
| Missing | Automatic proof that a recommendation is correct or useful | The product does not call an LLM to validate conclusions and does not infer correctness from ranking, links or feedback. |
| Missing | Automatic capture of all files an agent reads or all checks it runs | Reading-plan outcomes and verification records require explicit workflow actions; optional hooks cover only documented lifecycle events. |
| Missing | Broad, controlled evidence of reduced context without quality or time cost | Existing task records and experiments are not a substitute for the paired protocol in [Behavior evidence evaluation](behavior-evidence-evaluation.md). |

## Release rule

An optional or experimental capability must not be promoted as a recommended
release feature until both correctness and practical utility have evidence.
Correctness evidence must check output against source or other suitable ground
truth, including unresolved and false-link cases. Utility evidence must use
the paired protocol in [Behavior evidence evaluation](behavior-evidence-evaluation.md)
and report failures as well as successes. Until those conditions are met,
describe the capability as experimental and keep release claims narrow.

## First milestone: answers and acceptance

| Question | Current response surface | Status and example |
|---|---|---|
| Where do I start? | `repo_search`, entrypoints, existing ranking | Available passages; experimental ranking. Example: `handler.py:20–31`, matching request validation tokens, with source hash and excerpt. |
| What connects these points? | `repo_trace(evidence=true, anchor={path,symbol})` | Experimental. Example: `handler.py:24 handle -> storage.py:8 save`, with resolution method and both SHA-256 hashes. This is a static binding, never observed execution. |
| Where does reconstruction stop? | `evidence.gaps`, `evidence.hints`, per-file capabilities | Experimental. Example: caller line 28, target name `obj.save`, `unresolved_or_insufficient_proof`; receiver dispatch remains a hint. A depth, neighbor, result or work limit is an explicit boundary. |
| Can prior work be reused? | Existing notes/search and their file hashes; persisted index | Available note freshness and source evidence. Example: an old note remains stored but reports a changed referenced file after refresh. Analyzer invalidation preserves notes and tasks. Automatic saved investigation bundles are not introduced. |
| What verifies the hypothesis? | Existing test candidates and task checks | Available candidate/record surfaces; automatic path-to-check attachment is missing. Evidence trace explicitly returns `verification.status=no_linked_evidence` and never runs a new check to fill it. |

Per-file metadata distinguishes `indexed`, `text_search`, `structural`, analyzer
identity/fingerprint, extracted counts and partial errors. An indexed file need
not have structural analysis. A parsed file need not have resolved links.
Regex output alone cannot support an admitted evidence edge.

Acceptance requires source/target/line checks and no falsely resolved edges in
negative fixtures, including duplicate names, lexical shadowing, dynamic calls,
changed/deleted files and unavailable analyzers. Existing response fields stay
available. Evidence mode is opt-in and must not become a mandatory skill step.
Value propagation, complete runtime behavior and exhaustive test selection are
outside this milestone.
