# First natural-language use check

2026-10-16. One real diagnostic task, no coding-agent benchmark or model calls
outside the current conversation. No ranking or tokenizer changes were made.

## Task and initial retrieval

Question: “Perché la scansione include i log generati dagli esperimenti anche
quando sono esclusi tramite .gitignore?”

Called the live MCP repo_search once, limit 3, no path filter or target symbol.
Returned source hits:

1. init_agent/text_tokens.py — entries in a function-word list.
2. init_agent/trace.py — another query-noise word list.
3. experiments/agent-runs/README.md — event-log format examples.

None explained the requested exclusion behavior. Three memory notes concerned
other experiments or the MCP registry; they did not establish the cause either.
The structured result was approximately 5.7k JSON characters (not a measured
model-token count). The candidate channel reached its cap of 80 and the tool
reported incomplete coverage. No claim of search speed or token savings follows.

## Required fallback and verified cause

Ordinary rg search for gitignore/exclusion handling led to utils.py, then
scanner.py and git_boundary.py. Source inspection established:

- iter_project_files delegates to iter_indexable_files.
- Git-backed inventory uses ls-files -co --exclude-standard.
- _git_indexable_paths catches OSError/ValueError and returns None, causing a
  filesystem walk with init-agent exclusions, without parsing .gitignore.
- The actual run_git_read call raised “Git common directories and object
  alternates are not supported”. Normal git check-ignore did identify the
  experiment log as ignored.
- The main checkout has no top-level .git/commondir or object alternates file.
  It does have .git/worktrees/init-agent-local-maintenance/commondir. The current
  validator recursively visits the administrative tree and rejects that entry.

Thus the main checkout's worktree administrative entry triggers the Git refusal,
then the fallback inventory includes Git-ignored logs. This is a diagnostic
finding, not authorization to bypass Git boundary validation. No .git files,
worktrees, security checks or exclusion configuration were changed.

## Retrieval defect exposed by this task

The initial query tokenizes Perché as perch: identifier_terms uses an ASCII
regular expression before filtering FUNCTION_WORDS, so its perché entry cannot
remove the accented word. A direct terms('Perché') call confirms ['perch'].
Other Italian function words remain in the query. The resulting word-list hits
are consistent with this defect, but this single case does not establish that
Unicode normalization alone will fix ranking. Translation mismatch, ubiquitous
terms and query coverage remain separate possible contributors.

## Outcome

This use did not save exploration: the relevant exclusion implementation was
located by direct search after the MCP call. It did expose a reproducible input
normalization issue and a concrete explanation for unexpected indexed logs.
There was no separate blind baseline agent, so do not assign numerical agent
speed or token penalties. Next evaluate normalization on multiple languages and
identifier forms with exact-search controls; investigate Git fallback behavior
separately while preserving its security contract. Do not tune file weights to
make this one example pass.
