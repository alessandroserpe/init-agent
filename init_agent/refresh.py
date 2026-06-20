"""Incremental index refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .scanner import INDEX_VERSION, index_file, iter_project_files
from .utils import agent_dir, db_path, relative_path, sha256_file, utc_now


def refresh_index(root: Path) -> dict[str, Any]:
    if not agent_dir(root).is_dir() or not db_path(root).is_file():
        return {
            "status": "ERROR",
            "scanned_files": 0,
            "unchanged": 0,
            "added": [],
            "updated": [],
            "removed": [],
            "errors": ["init-agent is not initialized here. Run: init-agent init"],
            "suggested_commands": ["init-agent init"],
        }

    with GraphStore(root) as store:
        store.initialize()
        existing_hashes = store.file_hashes()
        if not existing_hashes:
            return {
                "status": "ERROR",
                "scanned_files": 0,
                "unchanged": 0,
                "added": [],
                "updated": [],
                "removed": [],
                "errors": ["No files are indexed yet. Run: init-agent map"],
                "suggested_commands": ["init-agent map"],
            }
        if store.get_meta("index_version") != INDEX_VERSION:
            return {
                "status": "ERROR",
                "scanned_files": 0,
                "unchanged": 0,
                "added": [],
                "updated": [],
                "removed": [],
                "errors": ["Index was created with an older extractor. Run: init-agent map"],
                "suggested_commands": ["init-agent map"],
            }

        run_id = store.begin_run("refresh")
        result = {
            "status": "OK",
            "scanned_files": 0,
            "unchanged": 0,
            "added": [],
            "updated": [],
            "removed": [],
            "errors": [],
        }
        try:
            real_files = iter_project_files(root)
            real_paths: set[str] = set()
            for path in real_files:
                rel_path = relative_path(path, root)
                real_paths.add(rel_path)
                result["scanned_files"] += 1
                try:
                    current_hash = sha256_file(path)
                    old_hash = existing_hashes.get(rel_path)
                    if old_hash is None:
                        index_file(root, path, store)
                        result["added"].append(rel_path)
                    elif old_hash != current_hash:
                        index_file(root, path, store)
                        result["updated"].append(rel_path)
                    else:
                        result["unchanged"] += 1
                except OSError as exc:
                    result["errors"].append(f"{rel_path}: {exc}")

            for rel_path in sorted(path for path in existing_hashes if path not in real_paths):
                store.delete_file_by_path(rel_path)
                result["removed"].append(rel_path)

            if result["added"] or result["updated"] or result["removed"]:
                store.rebuild_term_stats()
            store.set_meta("last_refresh", utc_now())
            store.finish_run(
                run_id,
                "ok" if not result["errors"] else "warning",
                {
                    "scanned_files": result["scanned_files"],
                    "unchanged": result["unchanged"],
                    "added": len(result["added"]),
                    "updated": len(result["updated"]),
                    "removed": len(result["removed"]),
                    "errors": len(result["errors"]),
                },
            )
            store.connection.commit()
        except Exception as exc:
            result["status"] = "ERROR"
            result["errors"].append(str(exc))
            store.finish_run(run_id, "error", {"error": str(exc)})
        return result
