# init-agent Run

Rules:

- Work only inside `/tmp/django-agent-comparison-hidden/runs/with_init_agent/worktree` and write your log only to `/tmp/django-agent-comparison-hidden/runs/with_init_agent/agent_log.md`.
- Start with init-agent before reading implementation files.
- Use init-agent follow-up commands when useful.
- Read `/tmp/django-agent-comparison-hidden/task.md`.
- Fix the regression.
- Run the targeted test command from the task.
- Log init-agent commands, files read, commands run, files modified, wrong turns/rework, final test result, and wall-clock estimate in `../agent_log.md`.
