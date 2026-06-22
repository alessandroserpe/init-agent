"""Graph export helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .utils import utc_now


EXPORT_FORMAT = "init-agent.graph.v1"


def export_graph(root: Path) -> dict[str, Any]:
    """Export the indexed graph without source file contents."""

    with GraphStore(root) as store:
        conn = store.connection
        files = [dict(row) for row in conn.execute("SELECT * FROM files ORDER BY path").fetchall()]
        file_by_id = {int(item["id"]): item for item in files}
        symbols = [
            _symbol_dict(dict(row))
            for row in conn.execute(
                """
                SELECT s.id, s.file_id, f.path AS file, s.name, s.kind, s.line, s.signature
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                ORDER BY f.path, s.line, s.name
                """
            ).fetchall()
        ]
        symbol_by_id = {int(item["id"]): item for item in symbols}
        relations = [
            _relation_dict(dict(row), file_by_id, symbol_by_id)
            for row in conn.execute(
                """
                SELECT id, source_type, source_id, relation, target_type, target_id, confidence, metadata_json
                FROM relations
                ORDER BY id
                """
            ).fetchall()
        ]
        commits = _commits(conn)
        feedback = [
            _feedback_dict(dict(row))
            for row in conn.execute(
                """
                SELECT id, query, path, rating, reason, source, created_at
                FROM orientation_feedback
                ORDER BY id
                """
            ).fetchall()
        ]
        runs = [
            _run_dict(dict(row))
            for row in conn.execute(
                """
                SELECT id, command, started_at, finished_at, status, summary_json
                FROM runs
                ORDER BY id
                """
            ).fetchall()
        ]
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM project_meta ORDER BY key").fetchall()}
        return {
            "format": EXPORT_FORMAT,
            "exported_at": utc_now(),
            "project": {
                "name": meta.get("project", root.name),
                "root": meta.get("root", str(root)),
                "git": meta.get("git"),
                "branch": meta.get("branch"),
                "meta": meta,
            },
            "stats": {
                "files": len(files),
                "symbols": len(symbols),
                "relations": len(relations),
                "git_commits": len(commits),
                "feedback": len(feedback),
                "runs": len(runs),
            },
            "files": files,
            "symbols": symbols,
            "relations": relations,
            "git_commits": commits,
            "feedback": feedback,
            "runs": runs,
        }


def _symbol_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "file_id": row["file_id"],
        "file": row["file"],
        "name": row["name"],
        "kind": row["kind"],
        "line": row["line"],
        "signature": row["signature"],
    }


def _relation_dict(
    row: dict[str, Any],
    file_by_id: dict[int, dict[str, Any]],
    symbol_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    metadata = _json_object(row.get("metadata_json"))
    item = {
        "id": row["id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "source_path": None,
        "relation": row["relation"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "target_path": None,
        "target_symbol": None,
        "confidence": row["confidence"],
        "metadata": metadata,
    }
    if row["source_type"] == "file":
        source = file_by_id.get(int(row["source_id"]))
        item["source_path"] = source["path"] if source else None
    if row["target_type"] == "file":
        item["target_path"] = str(row["target_id"])
    elif row["target_type"] == "symbol":
        try:
            target_symbol = symbol_by_id.get(int(row["target_id"]))
        except (TypeError, ValueError):
            target_symbol = None
        if target_symbol:
            item["target_symbol"] = {
                "id": target_symbol["id"],
                "name": target_symbol["name"],
                "kind": target_symbol["kind"],
                "file": target_symbol["file"],
                "line": target_symbol["line"],
            }
    return item


def _commits(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, hash, author, date, message FROM git_commits ORDER BY date DESC, id DESC").fetchall()
    commits = []
    for row in rows:
        files = [
            item["path"]
            for item in conn.execute(
                "SELECT path FROM git_commit_files WHERE commit_id = ? ORDER BY path",
                (row["id"],),
            ).fetchall()
        ]
        commits.append(
            {
                "id": row["id"],
                "hash": row["hash"],
                "author": row["author"],
                "date": row["date"],
                "message": row["message"],
                "files": files,
            }
        )
    return commits


def _feedback_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "query": row["query"],
        "path": row["path"],
        "rating": row["rating"],
        "reason": row["reason"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


def _run_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "command": row["command"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "summary": _json_object(row.get("summary_json")),
    }


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
