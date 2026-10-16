# Unicode normalization in full-text search

2026-10-16. This change fixes information loss; it does not establish a general
ranking advantage over ordinary agent search.

## Reproduction and implementation

ASCII-only extraction turned Perché into perch, defeating the existing function
word filter. It also split accented words incorrectly and dropped Chinese text.
New full-text search normalization uses NFC, Unicode word extraction and case
boundaries for Unicode identifiers. ASCII words retain the existing identifier
splitter. The FUNCTION_WORDS set, ranking, graph expansion and result limits are
unchanged. No language model, translation or case-specific weights are added.

The implementation is isolated in init_agent/search_tokens.py. The legacy graph
normalizer remains unchanged, including the user's earlier local edits. Source
index version 4 forces rebuilding old full-text rows even with identical file
hashes. Raw SQL notes are not rewritten; their query terms use the new normalizer.
NFC is canonical normalization, not transliteration or universal language
understanding. Coverage of every writing system is not established.

## Checks

Tests cover accented Italian, German, Spanish, Greek and Chinese words; composed
and decomposed accent forms; Unicode camel-case/acronyms; ASCII paths, symbols,
short technical names and digits; source and SQL note retrieval; and migration
from the previous source-index version without source edits. Existing retrieval,
freshness and transaction regressions also run. Before switching the full-text
normalizer, the new tests reproduced Unicode failures. Results are recorded in
/tmp/init-agent-normalization-before.log and /tmp/init-agent-normalization-after.log.

## Fixed-snapshot comparison

Run `python3 -m experiments.search_normalization`. Both index variants use the
same export of commit 4c155672ceb7522af8218cd0f79a25e9b01cc499 and the same ranking.
Only query/source normalization differs. Data:
experiments/search-normalization/comparison.json.

- The Italian question about Git exclusions no longer returns text_tokens.py
  first. It instead returns two .gitignore files and trace.py. The relevant
  inventory/validation implementation still does not appear: task unresolved.
- The Italian question about deletion of indexed files preserves già correctly
  but retains the same three returned paths. No demonstrated relevance gain.
- The English question about stale notes keeps identical paths and output size.
- Exact-symbol and exact-path controls keep identical paths and output size.

The separate before.json records the earlier live repository, whose dirty files,
logs and saved notes differ from the exported corpus. Do not compare that file
numerically to the exported after results. Five inspected requests and synthetic
Unicode checks are not a blind benchmark or evidence of agent token savings.

## Next issue remains separate

The first real-use investigation found that Git administrative validation rejects
worktree metadata, then filesystem fallback omits Git-ignore semantics. This
normalization change does not modify those security or inventory rules. Broad
cross-language intent and function-word noise remain unresolved retrieval issues.
