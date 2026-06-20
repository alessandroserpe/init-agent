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
                SELECT relation, target_type, target_id, MAX(confidence) AS confidence, metadata_json
                FROM relations
                WHERE source_type = 'file' AND source_id = ?
                  AND relation NOT IN ('defines', 'calls')
                GROUP BY relation, target_type, target_id
                ORDER BY confidence DESC, relation
                """,
                (file_row["id"],),
            )
        ]
        resolved_calls = _resolved_calls(conn, int(file_row["id"]))
        callers = _callers_for_file_symbols(conn, int(file_row["id"]))
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
            "resolved_calls": resolved_calls,
            "callers": callers,
            "commits": commits,
            "cochanged_files": cochanged,
        }


def _resolved_calls(conn: sqlite3.Connection, file_id: int) -> list[dict[str, object]]:
    source_row = conn.execute("SELECT language FROM files WHERE id = ?", (file_id,)).fetchone()
    source_language = str(source_row["language"] or "") if source_row else ""
    rows = conn.execute(
        """
        SELECT r.target_id AS name, MAX(r.confidence) AS confidence
        FROM relations r
        WHERE r.source_type = 'file'
          AND r.source_id = ?
          AND r.relation = 'calls'
          AND r.target_type = 'symbol_name'
        GROUP BY r.target_id
        ORDER BY r.target_id
        """,
        (file_id,),
    ).fetchall()
    result = []
    for row in rows:
        definitions = [
            dict(item)
            for item in _definition_rows_for_call(conn, str(row["name"]), source_language)
        ]
        result.append({"name": row["name"], "confidence": row["confidence"], "definitions": definitions})
    return result


def _definition_rows_for_call(conn: sqlite3.Connection, name: str, source_language: str) -> list[sqlite3.Row]:
    language_clause = "AND f.language = ?" if source_language == "php" else ""
    params: tuple[object, ...] = (name, source_language) if source_language == "php" else (name,)
    return conn.execute(
        f"""
        SELECT s.name, s.kind, s.line, f.path
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE s.name = ?
          AND s.kind IN ('function', 'method')
          {language_clause}
        ORDER BY f.path, s.line
        LIMIT 10
        """,
        params,
    ).fetchall()


def _callers_for_file_symbols(conn: sqlite3.Connection, file_id: int) -> list[dict[str, object]]:
    symbols = conn.execute("SELECT name FROM symbols WHERE file_id = ? ORDER BY name", (file_id,)).fetchall()
    callers: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for symbol in symbols:
        rows = conn.execute(
            """
            SELECT f.path, r.target_id AS name, r.confidence, r.metadata_json
            FROM relations r
            JOIN files f ON f.id = r.source_id
            WHERE r.source_type = 'file'
              AND r.relation = 'calls'
              AND r.target_type = 'symbol_name'
              AND r.target_id = ?
              AND f.id != ?
            ORDER BY f.path
            LIMIT 20
            """,
            (symbol["name"], file_id),
        ).fetchall()
        for row in rows:
            key = (row["path"], row["name"])
            if key in seen:
                continue
            seen.add(key)
            callers.append(dict(row))
    return callers[:20]


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
