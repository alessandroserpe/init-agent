# Agent Run Experiments

This directory is reserved for future paired agentic evaluations.

The deterministic benchmark in `experiments/evaluate.py` measures repository
orientation quality: whether expected useful files appear early in a generated
context pack.

Future agentic A/B experiments can store run artifacts here without mixing them
with the deterministic benchmark:

```text
experiments/agent-runs/
  <case-name>/
    baseline_run_01/
      prompt.md
      transcript.txt
      metrics.json
    init_agent_run_01/
      prompt.md
      transcript.txt
      metrics.json
```

These experiments should report limits clearly. They measure observed agent
behavior, not deterministic scoring quality.
