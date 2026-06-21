"""Install bundled agent skill templates."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Any


SKILL_NAME = "init-agent-orientation"


def install_codex_skill(destination_root: Path | None = None, force: bool = True) -> dict[str, Any]:
    target_root = destination_root or (Path.home() / ".codex" / "skills")
    source = resources.files("init_agent").joinpath("resources", "skills", SKILL_NAME)
    if not source.is_dir():
        raise FileNotFoundError(f"bundled skill not found: {SKILL_NAME}")

    target = target_root / SKILL_NAME
    if target.exists():
        if not force:
            raise FileExistsError(f"skill already exists: {target}")
        shutil.rmtree(target)

    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return {
        "skill": SKILL_NAME,
        "target": str(target),
        "installed": True,
    }
