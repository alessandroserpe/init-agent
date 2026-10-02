"""Graph export helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph_store import GraphStore
from .persisted_json import decode_persisted_object, CorruptMetadata, CORRUPT_METADATA_WARNING
from .signatures import minimize_signature
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
                SELECT s.id, s.file_id, f.path AS file, s.name, s.kind, s.line,
                       s.end_line, substr(s.signature, 1, 4096) AS signature, s.qualified_name, s.container_name
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
                SELECT id, source_type, source_id, relation, target_type, target_id,
                       context_symbol_id, confidence, metadata_json
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
            "warnings": [CORRUPT_METADATA_WARNING] if any(item.get("metadata_warning") for item in [*relations, *runs]) else [],
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
        "end_line": row["end_line"],
        "signature": minimize_signature(row["name"], row["kind"], row["signature"]),
        "qualified_name": row["qualified_name"],
        "container_name": row["container_name"],
    }


def _relation_dict(
    row: dict[str, Any],
    file_by_id: dict[int, dict[str, Any]],
    symbol_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    metadata_warning = False
    try:
        metadata = decode_persisted_object(row.get("metadata_json"), relation=True)
    except CorruptMetadata:
        metadata, metadata_warning = {}, True
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
        "context_symbol": None,
        "confidence": row["confidence"],
        "metadata": metadata,
        "metadata_warning": CORRUPT_METADATA_WARNING if metadata_warning else "",
    }
    if row["source_type"] == "file":
        source = file_by_id.get(int(row["source_id"]))
        item["source_path"] = source["path"] if source else None
    elif row["source_type"] == "symbol":
        source_symbol = symbol_by_id.get(int(row["source_id"]))
        if source_symbol:
            item["source_path"] = source_symbol["file"]
            item["source_symbol"] = {
                "id": source_symbol["id"],
                "name": source_symbol["name"],
                "qualified_name": source_symbol["qualified_name"],
                "kind": source_symbol["kind"],
                "line": source_symbol["line"],
            }
    if row.get("context_symbol_id") is not None:
        context_symbol = symbol_by_id.get(int(row["context_symbol_id"]))
        if context_symbol:
            item["context_symbol"] = {
                "id": context_symbol["id"],
                "name": context_symbol["name"],
                "qualified_name": context_symbol["qualified_name"],
                "kind": context_symbol["kind"],
                "file": context_symbol["file"],
                "line": context_symbol["line"],
            }
    if row["target_type"] == "file":
        item["target_path"] = str(row["target_id"])
    elif row["target_type"] in {"symbol", "resolved_symbol"}:
        try:
            target_symbol = symbol_by_id.get(int(row["target_id"]))
        except (TypeError, ValueError):
            target_symbol = None
        if target_symbol:
            item["target_path"] = target_symbol["file"]
            item["target_symbol"] = {
                "id": target_symbol["id"],
                "name": target_symbol["name"],
                "qualified_name": target_symbol["qualified_name"],
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
    try:
        summary = decode_persisted_object(row.get("summary_json"))
        warning = ""
    except CorruptMetadata:
        summary, warning = {}, CORRUPT_METADATA_WARNING
    return {
        "id": row["id"], "command": row["command"],
        "started_at": row["started_at"], "finished_at": row["finished_at"],
        "status": row["status"], "summary": summary, "metadata_warning": warning,
    }
