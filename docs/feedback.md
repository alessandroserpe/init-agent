# Feedback

`init-agent feedback` stores local orientation feedback after a user, agent or
benchmark verifies whether a suggested file was useful.

It does not call an LLM and does not store source code.

## Ratings

- `crucial`: verified as one of the first files an agent should read
- `useful`: relevant supporting file
- `neutral`: recorded context without ranking effect
- `noisy`: matched but was not useful for the task
- `missing`: useful file that was absent from the context pack

## Commands

```bash
init-agent feedback add "fix login session bug" src/auth/session.py --rating crucial --source agent
init-agent feedback add "fix login session bug" README.md --rating noisy --reason "matched words but not useful"
init-agent feedback list
init-agent feedback list --json
init-agent feedback explain "fix login session bug"
init-agent feedback explain "fix login session bug" --all --json
init-agent feedback export --json
init-agent feedback import feedback.json --json
init-agent feedback clear --path README.md
init-agent feedback clear --all
```

## Ranking Effect

Feedback affects `context` and `run` only when query tokens are similar enough.
The score contribution is capped, so old feedback cannot override strong direct
path, filename, symbol or call matches.

Context reasons stay explicit:

```text
previously marked crucial for similar query
previously marked noisy for similar query
```

Use `feedback explain` when a repeated query improves or gets worse and you
want to see which local feedback entries matched, their token similarity and
their bounded score contribution. With `--all`, it also shows feedback that was
ignored because it was below the similarity threshold or pointed to a file that
is no longer indexed.

## Safety

Feedback should be recorded only after files are verified. Do not mark files as
useful or noisy from ranking alone.
