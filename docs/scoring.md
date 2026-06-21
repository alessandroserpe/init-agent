# Scoring

`init-agent context` and `init-agent run "<task>"` use simple metadata-only
ranking. They do not read full source files during scoring and do not call an
LLM.

## Signals

The scorer considers:

- file paths and filenames
- symbol names
- file roles and languages
- Git commit messages and changed files, when imported
- simple graph relations such as imports/includes and PHP function calls
- local orientation feedback, when present

## Token Weighting

Query tokens are weighted by local rarity across indexed paths, filenames,
symbol names, roles, languages and commit messages. Common repository terms are
downweighted so specific terms such as `login` can beat broad terms such as
`admin`.

Generic request words such as `file`, `repo`, `repository` and `project` are
ignored. Small language function words such as `why`, `where`, `and`, `after`,
`perche`, `dove` and similar terms are also filtered before scoring.

## File Match Priority

Direct path matches are strong signals. Filename matches are stronger than
generic path matches.

Path and filename matching is boundary-aware, so tiny incidental substrings do
not dominate natural-language queries. Conservative soft matches help with
close lexical variants without hardcoded project-specific synonyms.

## Symbols, Commits And Relations

Symbol matches are useful, but repeated matches for the same token in one file
do not stack endlessly.

Commit message matches are secondary signals. They can help identify recently
touched files, but should not dominate direct path or symbol matches.

Relation boosts are capped so a file cannot win only because it has many graph
edges. Context output also limits repeated `related to ...` reasons.

## Role And Type Weighting

Role and language matches contribute a small relevance boost.

Operational queries prefer source files over likely-supporting files:

- test files are reduced for non-test-aware queries
- asset/style files are reduced for non-UI queries
- migration/SQL files are reduced for non-database queries
- documentation files are reduced for non-docs queries
- examples/playgrounds are reduced for non-example queries

The penalties are not applied when the query clearly asks for that type of file,
for example `css login`, `migration admin permissions`, `readme installazione`
or `pytest fixture`.

Source files with backend/code extensions get a small preference.

## Output Limits

Context packs return at most:

- 10 candidate files
- 10 related symbols
- 5 recent commits

Each recent commit includes at most 10 changed files in output. Large commits
include `total_files` and `files_truncated`.

## Limits

Scoring is heuristic. It is designed to tell an agent where to start, not to
prove what code is correct. Agents should still verify by reading files.
