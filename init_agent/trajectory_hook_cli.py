"""Minimal, fail-open entrypoint used by Codex lifecycle hooks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .trajectory import find_initialized_trajectory_root, ingest_codex_hook


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        root = find_initialized_trajectory_root(payload.get("cwd")) or find_initialized_trajectory_root(Path.cwd())
        if root is None:
            return 0
        ingest_codex_hook(root, payload, source="codex_hook")
    except Exception:
        # Observability must never interrupt or steer the coding agent.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
