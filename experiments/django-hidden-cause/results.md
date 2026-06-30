# Hidden-Cause Django Comparison Results

Repository: Django shallow clone in `/tmp`.

Goal of this experiment:

- prompt does not name exact function/file/module;
- failing test is in a higher-level template response test;
- multiple paths are plausible: template response, template filters, default filters, HTML utilities, settings;
- expected advantage is reaching the correct area sooner, not necessarily fewer total commands.

## Seed

Controlled low-level cause:

```python
# django/utils/html.py
trailing_punctuation_chars = ".,:;"
```

High-level failing test:

```text
template_tests.test_response.GeneratedLinkRenderingRegressionTest
```

Targeted test command:

```bash
PYTHONPATH=$PWD /tmp/django-init-agent-venv/bin/python tests/runtests.py template_tests.test_response.GeneratedLinkRenderingRegressionTest --parallel 1 --verbosity 1
```

## Result

| Metric | baseline_no_init_agent | with_init_agent |
| --- | ---: | ---: |
| Outcome | PASS | PASS |
| Targeted tests | 1 OK | 1 OK |
| Approx logged wall-clock | ~8 min | ~1.5 min |
| Logged files read | 7 | 6 |
| Correct source file read position | 3rd | 3rd |
| Source/test files modified | 2 | 2 |
| Logged commands | 22 | 11 plus 5 init-agent commands |
| init-agent commands | 0 | 5 |
| Wrong turns / rework | broad noisy rg; HTTPS warning after source fix | noisy Generated match; HTTPS warning after source fix |

## Human Read

This is closer to the comparison we wanted.

Both agents fixed the underlying source bug in `django/utils/html.py` and both had
to adjust the high-level regression test with `@override_settings(URLIZE_ASSUME_HTTPS=True)` because the new test expected HTTPS for a bare domain.

The important difference is work shape:

- baseline used broad text search and inspected more surrounding settings/test areas;
- init-agent also had a noisy first signal (`Generated` matched generated-field code), but narrowed quickly to `django/utils/html.py`;
- both reached the correct source file as the third file read, but init-agent logged far less elapsed time and fewer manual exploration commands.

This is not a perfect benchmark because the new high-level test introduced a secondary HTTPS-setting issue. But that issue affected both agents equally and is itself realistic: a high-level regression often exposes framework settings behavior along the way.

## Raw Logs

- `logs/baseline_agent_log.md`
- `logs/init_agent_log.md`
