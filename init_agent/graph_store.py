"""SQLite persistence for the local project graph."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .utils import db_path, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS project_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    extension TEXT,
    language TEXT,
    role TEXT,
    size INTEGER,
    sha256 TEXT,
    modified_at TEXT,
    indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    line INTEGER,
    signature TEXT,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    relation TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    confidence REAL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS git_commits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT NOT NULL UNIQUE,
    author TEXT,
    date TEXT,
    message TEXT
);

CREATE TABLE IF NOT EXISTS git_commit_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    FOREIGN KEY(commit_id) REFERENCES git_commits(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS term_stats (
    term TEXT NOT NULL,
    source TEXT NOT NULL,
    document_count INTEGER NOT NULL,
    total_count INTEGER NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY(term, source)
);

CREATE TABLE IF NOT EXISTS orientation_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    query_tokens_json TEXT NOT NULL,
    path TEXT NOT NULL,
    rating TEXT NOT NULL,
    reason TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class GraphStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = db_path(root)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def set_meta(self, key: str, value: Any) -> None:
        stored = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
        self.connection.execute(
            "INSERT INTO project_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, stored),
        )

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.connection.execute("SELECT value FROM project_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def begin_run(self, command: str) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs(command, started_at, status) VALUES(?, ?, ?)",
            (command, utc_now(), "running"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, summary: dict[str, Any] | None = None) -> None:
        self.connection.execute(
            "UPDATE runs SET finished_at = ?, status = ?, summary_json = ? WHERE id = ?",
            (utc_now(), status, json.dumps(summary or {}, sort_keys=True), run_id),
        )
        self.connection.commit()

    def upsert_file(self, record: dict[str, Any]) -> int:
        self.connection.execute(
            """
            INSERT INTO files(path, extension, language, role, size, sha256, modified_at, indexed_at)
            VALUES(:path, :extension, :language, :role, :size, :sha256, :modified_at, :indexed_at)
            ON CONFLICT(path) DO UPDATE SET
                extension=excluded.extension,
                language=excluded.language,
                role=excluded.role,
                size=excluded.size,
                sha256=excluded.sha256,
                modified_at=excluded.modified_at,
                indexed_at=excluded.indexed_at
            """,
            record,
        )
        row = self.connection.execute("SELECT id FROM files WHERE path = ?", (record["path"],)).fetchone()
        return int(row["id"])

    def replace_file_symbols_and_relations(
        self,
        file_id: int,
        symbols: Iterable[dict[str, Any]],
        relations: Iterable[dict[str, Any]],
    ) -> None:
        symbol_items = list(symbols)
        relation_items = list(relations)
        self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM relations WHERE source_type = 'file' AND source_id = ?", (file_id,))
        self.connection.executemany(
            "INSERT INTO symbols(file_id, name, kind, line, signature) VALUES(?, ?, ?, ?, ?)",
            [(file_id, item["name"], item["kind"], item["line"], item["signature"]) for item in symbol_items],
        )
        symbol_rows = self.connection.execute(
            "SELECT id, name, kind, line FROM symbols WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        relation_items.extend(
            {
                "relation": "defines",
                "target_type": "symbol",
                "target_id": row["id"],
                "confidence": 1.0,
                "metadata": {"name": row["name"], "kind": row["kind"], "line": row["line"]},
            }
            for row in symbol_rows
        )
        self.connection.executemany(
            """
            INSERT INTO relations(source_type, source_id, relation, target_type, target_id, confidence, metadata_json)
            VALUES('file', ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    file_id,
                    item["relation"],
                    item["target_type"],
                    str(item["target_id"]),
                    item.get("confidence", 0.75),
                    json.dumps(item.get("metadata", {}), sort_keys=True),
                )
                for item in relation_items
            ],
        )

    def replace_git_history(self, commits: Iterable[dict[str, Any]]) -> None:
        self.connection.execute("DELETE FROM git_commit_files")
        self.connection.execute("DELETE FROM git_commits")
        for commit in commits:
            cursor = self.connection.execute(
                "INSERT INTO git_commits(hash, author, date, message) VALUES(?, ?, ?, ?)",
                (commit["hash"], commit["author"], commit["date"], commit["message"]),
            )
            commit_id = int(cursor.lastrowid)
            self.connection.executemany(
                "INSERT INTO git_commit_files(commit_id, path) VALUES(?, ?)",
                [(commit_id, path) for path in commit.get("files", [])],
            )
        self.connection.commit()

    def rebuild_term_stats(self) -> int:
        from .term_stats import rebuild_term_stats

        rows = rebuild_term_stats(self.connection)
        self.set_meta("term_stats_updated_at", utc_now())
        self.connection.commit()
        return rows

    def file_hashes(self) -> dict[str, str]:
        rows = self.connection.execute("SELECT path, sha256 FROM files").fetchall()
        return {row["path"]: row["sha256"] for row in rows}

    def delete_file_by_path(self, path: str) -> None:
        row = self.connection.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
        if not row:
            return
        file_id = int(row["id"])
        symbol_ids = [
            str(item["id"])
            for item in self.connection.execute("SELECT id FROM symbols WHERE file_id = ?", (file_id,)).fetchall()
        ]
        self.connection.execute("DELETE FROM relations WHERE source_type = 'file' AND source_id = ?", (file_id,))
        self.connection.execute("DELETE FROM relations WHERE target_type = 'file' AND target_id = ?", (path,))
        if symbol_ids:
            placeholders = ",".join("?" for _ in symbol_ids)
            self.connection.execute(f"DELETE FROM relations WHERE target_type = 'symbol' AND target_id IN ({placeholders})", symbol_ids)
        self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM files WHERE id = ?", (file_id,))

    def counts(self) -> dict[str, int]:
        return {
            "files": self._count("files"),
            "symbols": self._count("symbols"),
            "relations": self._count("relations"),
            "git_commits": self._count("git_commits"),
        }

    def latest_map_time(self) -> str | None:
        row = self.connection.execute(
            "SELECT finished_at FROM runs WHERE command = 'map' AND status = 'ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["finished_at"] if row else None

    def _count(self, table: str) -> int:
        row = self.connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        return int(row["count"])
