"""Install bundled agent skill templates."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from . import __version__


SKILL_NAME = "init-agent-orientation"
SKILL_MANIFEST = ".init-agent-skill.json"


def codex_skill_status(destination_root: Path | None = None) -> dict[str, Any]:
    target_root = destination_root or (Path.home() / ".codex" / "skills")
    source = resources.files("init_agent").joinpath("resources", "skills", SKILL_NAME)
    target = target_root / SKILL_NAME
    bundled_file = source.joinpath("SKILL.md")
    installed_file = target / "SKILL.md"
    manifest_path = target / SKILL_MANIFEST
    bundled_sha256 = _sha256_file(Path(str(bundled_file))) if bundled_file.is_file() else ""

    base = {
        "skill": SKILL_NAME,
        "target": str(target),
        "bundled_version": __version__,
        "bundled_sha256": bundled_sha256,
    }
    if not installed_file.is_file():
        return {**base, "installed": False, "current": False, "status": "missing", "installed_version": ""}

    installed_sha256 = _sha256_file(installed_file)
    manifest = _read_manifest(manifest_path)
    recorded_sha256 = str(manifest.get("installed_sha256", ""))
    installed_version = str(manifest.get("package_version", ""))
    if installed_sha256 == bundled_sha256:
        status = "current" if manifest else "current_untracked"
        return {
            **base,
            "installed": True,
            "current": True,
            "status": status,
            "installed_version": installed_version,
            "installed_sha256": installed_sha256,
            "modified": False,
        }

    modified = bool(recorded_sha256 and installed_sha256 != recorded_sha256)
    status = "modified" if modified else ("outdated" if manifest else "outdated_or_modified")
    return {
        **base,
        "installed": True,
        "current": False,
        "status": status,
        "installed_version": installed_version,
        "installed_sha256": installed_sha256,
        "modified": modified,
    }


def install_codex_skill(destination_root: Path | None = None, force: bool = True) -> dict[str, Any]:
    target_root = destination_root or (Path.home() / ".codex" / "skills")
    source = resources.files("init_agent").joinpath("resources", "skills", SKILL_NAME)
    if not source.is_dir():
        raise FileNotFoundError(f"bundled skill not found: {SKILL_NAME}")

    target = target_root / SKILL_NAME
    previous = codex_skill_status(target_root)
    backup_path: Path | None = None
    if target.exists():
        if not force:
            raise FileExistsError(f"skill already exists: {target}")
        if previous["status"] in {"modified", "outdated_or_modified"}:
            backup_path = _backup_skill(target)
        shutil.rmtree(target)

    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    installed_sha256 = _sha256_file(target / "SKILL.md")
    (target / SKILL_MANIFEST).write_text(
        json.dumps(
            {
                "contract": "init-agent.skill-install.v1",
                "skill": SKILL_NAME,
                "package_version": __version__,
                "installed_sha256": installed_sha256,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "skill": SKILL_NAME,
        "target": str(target),
        "installed": True,
        "status": "installed",
        "version": __version__,
        "previous_status": previous["status"],
        "backup_path": str(backup_path) if backup_path else None,
    }


def sync_codex_skill(destination_root: Path | None = None) -> dict[str, Any]:
    before = codex_skill_status(destination_root)
    if before["current"] and before["status"] == "current":
        return {
            "skill": SKILL_NAME,
            "target": before["target"],
            "installed": True,
            "updated": False,
            "status": "current",
            "version": __version__,
            "previous_status": before["status"],
            "backup_path": None,
        }
    result = install_codex_skill(destination_root)
    result["updated"] = before["installed"]
    result["status"] = "updated" if before["installed"] else "installed"
    return result


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_skill(target: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    backup = target.parent / f"{target.name}.bak-{timestamp}"
    shutil.copytree(target, backup)
    return backup
