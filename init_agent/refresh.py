"""Incremental index refresh."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .repo_budget import WorkBudgetExceeded, bounded_operation
from .graph_store import GraphStore
from .parse_budget import ParseFailure
from .relation_resolver import rebuild_resolved_relations
from .scanner import INDEX_VERSION, index_file, iter_project_files
from .repo_files import repo_snapshot
from .utils import agent_dir, db_path, relative_path, utc_now
from .analysis_capabilities import current_fingerprint, ensure_table, load_capabilities
from .language_detector import detect_language


@bounded_operation
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
        ensure_table(store)
        existing_hashes = store.file_hashes()
        existing_analysis = load_capabilities(store)
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
                    snapshot = repo_snapshot(root, rel_path)
                    current_hash = snapshot.sha256
                    old_hash = existing_hashes.get(rel_path)
                    capabilities = existing_analysis.get(rel_path, {})
                    analyzer_stale = capabilities.get("analyzer_fingerprint") != current_fingerprint(detect_language(path))
                    summary = {}
                    if old_hash is None:
                        summary = index_file(root, path, store, snapshot=snapshot)
                        result["added"].append(rel_path)
                    elif old_hash != current_hash:
                        summary = index_file(root, path, store, snapshot=snapshot)
                        result["updated"].append(rel_path)
                    elif analyzer_stale:
                        summary = index_file(root, path, store, snapshot=snapshot)
                        result["updated"].append(rel_path)
                    else:
                        result["unchanged"] += 1
                    if summary.get("errors") and len(result["errors"]) < 50:
                        result["errors"].append(f"{rel_path}: {summary['errors'][0]}")
                except (OSError, ParseFailure, RecursionError, MemoryError) as exc:
                    store.delete_file_by_path(rel_path)
                    result["removed"].append(rel_path)
                    if len(result["errors"]) < 50:
                        reason = str(exc) if isinstance(exc, ParseFailure) else type(exc).__name__
                        result["errors"].append(f"{rel_path[:300]}: {reason}")

            for rel_path in sorted(path for path in existing_hashes if path not in real_paths):
                store.delete_file_by_path(rel_path)
                result["removed"].append(rel_path)

            # Compiler output depends on imported sources and configuration as
            # well as its own bytes. Reanalyse only affected unchanged files.
            current_hashes = store.file_hashes()
            changed = set(result["added"] + result["updated"] + result["removed"])
            for rel_path, analysis in existing_analysis.items():
                if rel_path not in real_paths or rel_path in changed or analysis.get("analyzer") != "typescript-compiler":
                    continue
                dependencies = dict(store.connection.execute("SELECT d.path,d.sha256 FROM analysis_dependencies d JOIN files f ON f.id=d.file_id WHERE f.path=?", (rel_path,)))
                config_changed = any(Path(p).name in {"tsconfig.json", "package.json"} for p in changed)
                if result["added"] or result["removed"] or config_changed or any(current_hashes.get(p) != sha for p, sha in dependencies.items()):
                    index_file(root, root / rel_path, store)
                    result["updated"].append(rel_path)
                    result["unchanged"] -= 1

            if result["added"] or result["updated"] or result["removed"]:
                result["resolved_relations"] = rebuild_resolved_relations(store)
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
        except WorkBudgetExceeded:
            store.connection.rollback()
            raise
        except Exception as exc:
            result["status"] = "ERROR"
            result["errors"].append(str(exc))
            store.finish_run(run_id, "error", {"error": str(exc)})
        return result
