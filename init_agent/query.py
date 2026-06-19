"""Simple non-AI search and related-file queries."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .graph_store import GraphStore


def search(root: Path, text: str, limit: int = 20) -> list[dict[str, object]]:
    term = text.strip().lower()
    if not term:
        return []
    with GraphStore(root) as store:
        conn = store.connection
        results: list[dict[str, object]] = []
        results.extend(_search_files(conn, term))
        results.extend(_search_symbols(conn, term))
        results.extend(_search_commits(conn, term))
        ranked = sorted(results, key=lambda item: (-int(item["score"]), str(item["label"])))
        return ranked[:limit]


def related(root: Path, file_path: str) -> dict[str, object] | None:
    normalized = Path(file_path).as_posix().lstrip("./")
    with GraphStore(root) as store:
        conn = store.connection
        file_row = conn.execute("SELECT * FROM files WHERE path = ?", (normalized,)).fetchone()
        if not file_row:
            return None
        symbols = [dict(row) for row in conn.execute("SELECT name, kind, line FROM symbols WHERE file_id = ? ORDER BY line", (file_row["id"],))]
        relations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT relation, target_type, target_id, confidence, metadata_json
                FROM relations
                WHERE source_type = 'file' AND source_id = ?
                ORDER BY confidence DESC, relation
                """,
                (file_row["id"],),
            )
        ]
        commits = [
            dict(row)
            for row in conn.execute(
                """
                SELECT c.id, c.hash, c.author, c.date, c.message
                FROM git_commits c
                JOIN git_commit_files f ON f.commit_id = c.id
                WHERE f.path = ?
                ORDER BY c.date DESC
                LIMIT 10
                """,
                (normalized,),
            )
        ]
        commit_ids = [commit["id"] for commit in commits]
        cochanged: list[dict[str, object]] = []
        if commit_ids:
            placeholders = ",".join("?" for _ in commit_ids)
            cochanged = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT path, COUNT(*) AS commits_together
                    FROM git_commit_files
                    WHERE commit_id IN ({placeholders}) AND path != ?
                    GROUP BY path
                    ORDER BY commits_together DESC, path
                    LIMIT 20
                    """,
                    (*commit_ids, normalized),
                )
            ]
        return {
            "file": dict(file_row),
            "symbols": symbols,
            "relations": relations,
            "commits": commits,
            "cochanged_files": cochanged,
        }


def _search_files(conn: sqlite3.Connection, term: str) -> list[dict[str, object]]:
    rows = conn.execute("SELECT path, role, language FROM files").fetchall()
    results = []
    for row in rows:
        score = 0
        path = row["path"].lower()
        role = (row["role"] or "").lower()
        if term == path:
            score += 100
        if term in path:
            score += 40
        if term == role:
            score += 35
        elif term in role:
            score += 20
        if score:
            results.append({"type": "file", "label": row["path"], "detail": f"{row['language']} / {row['role']}", "score": score})
    return results


def _search_symbols(conn: sqlite3.Connection, term: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT s.name, s.kind, s.line, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        """
    ).fetchall()
    results = []
    for row in rows:
        name = row["name"].lower()
        score = 0
        if term == name:
            score += 90
        elif term in name:
            score += 50
        if score:
            detail = f"{row['kind']} in {row['path']}:{row['line']}"
            results.append({"type": "symbol", "label": row["name"], "detail": detail, "score": score})
    return results


def _search_commits(conn: sqlite3.Connection, term: str) -> list[dict[str, object]]:
    rows = conn.execute("SELECT hash, author, date, message FROM git_commits").fetchall()
    results = []
    for row in rows:
        message = (row["message"] or "").lower()
        score = 0
        if term in message:
            score += 30
        if score:
            label = f"{row['hash'][:10]} {row['message']}"
            results.append({"type": "commit", "label": label, "detail": f"{row['date']} {row['author']}", "score": score})
    return results
