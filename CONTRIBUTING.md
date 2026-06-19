# Contributing

Thanks for considering a contribution to `init-agent`.

## Development Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run tests:

```bash
python -m unittest discover -s tests -v
```

## Principles

- Keep the project local-first and privacy-preserving.
- Do not add mandatory external dependencies without a strong reason.
- Do not add built-in LLM execution to core commands.
- Store metadata, symbols and relations, not full source code.
- Prefer clear, small modules over clever abstractions.
- Keep terminal output readable and JSON output stable.

## Pull Requests

Before opening a pull request:

- Add or update `unittest` coverage for behavior changes.
- Update `README.md` and `CHANGELOG.md` when user-facing behavior changes.
- Run the full test suite.
- Keep changes focused on one feature or fix.

## Security And Privacy

Please do not submit changes that send repository contents to external services by default. Any future integration with external tools should be explicit and opt-in.
