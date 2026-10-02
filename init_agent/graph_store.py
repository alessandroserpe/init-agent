"""SQLite persistence for the local project graph."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .repo_budget import BudgetConnection
from .private_files import private_open
from .signatures import minimize_signature
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
    qualified_name TEXT,
    container_name TEXT,
    end_line INTEGER,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    relation TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    context_symbol_id INTEGER,
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

CREATE TABLE IF NOT EXISTS file_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    source TEXT NOT NULL,
    weight REAL NOT NULL,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
    UNIQUE(file_id, tag, source)
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

CREATE TABLE IF NOT EXISTS agent_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    scope TEXT,
    topic TEXT,
    query TEXT,
    note TEXT NOT NULL,
    note_tokens_json TEXT NOT NULL,
    tags_json TEXT,
    file_sha256 TEXT,
    evidence TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    topic TEXT,
    summary TEXT,
    files_json TEXT NOT NULL,
    memory_ids_json TEXT NOT NULL,
    feedback_ids_json TEXT NOT NULL,
    tests_json TEXT NOT NULL,
    remaining_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_task_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    note TEXT NOT NULL,
    files_json TEXT NOT NULL,
    memory_ids_json TEXT NOT NULL,
    feedback_ids_json TEXT NOT NULL,
    tests_json TEXT NOT NULL,
    remaining_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reading_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    query_tokens_json TEXT NOT NULL,
    read_budget INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'real',
    summary TEXT,
    file_manifest_blob BLOB,
    finished_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reading_plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    action TEXT,
    read_priority TEXT,
    read_budget_rank INTEGER,
    confidence TEXT,
    base_rank INTEGER,
    base_score REAL,
    rank_lift INTEGER,
    signal_contributions_json TEXT,
    sources_json TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    reason TEXT,
    FOREIGN KEY(plan_id) REFERENCES reading_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reading_plan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    event TEXT NOT NULL,
    path TEXT NOT NULL,
    note TEXT,
    feedback_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES reading_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reading_plan_workstreams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    workstream_key TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    role TEXT NOT NULL,
    model_tier TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    access_mode TEXT NOT NULL,
    scope_paths_json TEXT NOT NULL,
    depends_on_json TEXT NOT NULL,
    status TEXT NOT NULL,
    agent_name TEXT,
    report_json TEXT,
    orchestrator_decision TEXT,
    orchestrator_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT,
    FOREIGN KEY(plan_id) REFERENCES reading_plans(id) ON DELETE CASCADE,
    UNIQUE(plan_id, workstream_key)
);

CREATE TABLE IF NOT EXISTS trajectory_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_session_id TEXT NOT NULL,
    cwd TEXT,
    model TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT,
    first_event_at TEXT NOT NULL,
    last_event_at TEXT NOT NULL,
    UNIQUE(source, external_session_id)
);

CREATE TABLE IF NOT EXISTS trajectory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    turn_id TEXT,
    event_name TEXT NOT NULL,
    event_key TEXT NOT NULL,
    tool_name TEXT,
    tool_use_id TEXT,
    agent_id TEXT,
    agent_type TEXT,
    status TEXT,
    duration_ms INTEGER,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES trajectory_sessions(id) ON DELETE CASCADE
);

"""


class GraphStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = db_path(root)
        # Pre-create with 0600 so SQLite sidecars inherit a private database mode.
        with private_open(self.path, "a"):
            pass
        self.connection = sqlite3.connect(self.path, timeout=1, factory=BudgetConnection)
        try:
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 1000")
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self._migrate_schema()
        self.connection.commit()

    def _migrate_schema(self) -> None:
        self._ensure_column("agent_notes", "file_sha256", "TEXT")
        self._ensure_column("agent_notes", "evidence", "TEXT")
        self._ensure_column("agent_notes", "scope", "TEXT")
        self._ensure_column("agent_notes", "tags_json", "TEXT")
        self._ensure_column("reading_plans", "kind", "TEXT")
        self._ensure_column("reading_plans", "file_manifest_blob", "BLOB")
        self._ensure_column("reading_plan_items", "base_rank", "INTEGER")
        self._ensure_column("reading_plan_items", "base_score", "REAL")
        self._ensure_column("reading_plan_items", "rank_lift", "INTEGER")
        self._ensure_column("reading_plan_items", "signal_contributions_json", "TEXT")
        self._ensure_column("symbols", "qualified_name", "TEXT")
        self._ensure_column("symbols", "container_name", "TEXT")
        self._ensure_column("symbols", "end_line", "INTEGER")
        self._ensure_column("relations", "context_symbol_id", "INTEGER")
        self._ensure_column("trajectory_events", "event_key", "TEXT")
        self.connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
            CREATE INDEX IF NOT EXISTS idx_relations_source
                ON relations(source_type, source_id, relation, target_type);
            CREATE INDEX IF NOT EXISTS idx_relations_target
                ON relations(target_type, target_id, relation);
            CREATE INDEX IF NOT EXISTS idx_relations_context_symbol
                ON relations(context_symbol_id);
            CREATE INDEX IF NOT EXISTS idx_trajectory_events_session
                ON trajectory_events(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_trajectory_events_tool_use
                ON trajectory_events(session_id, tool_use_id, event_name);
            CREATE INDEX IF NOT EXISTS idx_trajectory_events_created
                ON trajectory_events(created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_trajectory_events_identity
                ON trajectory_events(session_id, event_key)
                WHERE event_key IS NOT NULL AND event_key != '';
            """
        )

    def _ensure_column(self, table: str, column: str, column_type: str) -> None:
        rows = self.connection.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column not in existing:
            try:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

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
        previous_symbol_ids = [
            str(row["id"])
            for row in self.connection.execute("SELECT id FROM symbols WHERE file_id = ?", (file_id,)).fetchall()
        ]
        if previous_symbol_ids:
            placeholders = ",".join("?" for _ in previous_symbol_ids)
            self.connection.execute(
                f"DELETE FROM relations WHERE source_type = 'symbol' AND source_id IN ({placeholders})",
                previous_symbol_ids,
            )
            self.connection.execute(
                f"DELETE FROM relations WHERE target_type IN ('symbol', 'resolved_symbol') AND target_id IN ({placeholders})",
                previous_symbol_ids,
            )
        self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM relations WHERE source_type = 'file' AND source_id = ?", (file_id,))
        self.connection.executemany(
            """
            INSERT INTO symbols(
                file_id, name, kind, line, signature, qualified_name, container_name, end_line
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    file_id,
                    item["name"],
                    item["kind"],
                    item["line"],
                    minimize_signature(item["name"], item["kind"], item["signature"]),
                    item.get("qualified_name") or item["name"],
                    item.get("container_name") or "",
                    item.get("end_line"),
                )
                for item in symbol_items
            ],
        )
        symbol_rows = self.connection.execute(
            "SELECT id, name, kind, line, qualified_name FROM symbols WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        symbol_by_qualified_name = {
            str(row["qualified_name"] or row["name"]): int(row["id"])
            for row in symbol_rows
        }
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
            INSERT INTO relations(
                source_type, source_id, relation, target_type, target_id,
                context_symbol_id, confidence, metadata_json
            ) VALUES('file', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    file_id,
                    item["relation"],
                    item["target_type"],
                    str(item["target_id"]),
                    symbol_by_qualified_name.get(str(item.get("metadata", {}).get("source_qualified_name") or "")),
                    item.get("confidence", 0.75),
                    json.dumps(
                        {
                            key: value
                            for key, value in item.get("metadata", {}).items()
                            if key != "source_qualified_name"
                        },
                        sort_keys=True,
                    ),
                )
                for item in relation_items
            ],
        )

    def replace_file_tags(self, file_id: int, tags: Iterable[dict[str, Any]]) -> None:
        tag_items = list(tags)
        self.connection.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        self.connection.executemany(
            """
            INSERT INTO file_tags(file_id, tag, source, weight)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(file_id, tag, source) DO UPDATE SET weight=excluded.weight
            """,
            [
                (
                    file_id,
                    str(item["tag"]),
                    str(item.get("source") or "auto"),
                    float(item.get("weight", 1.0)),
                )
                for item in tag_items
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
        self.connection.execute("DELETE FROM relations WHERE target_type = 'resolved_file' AND target_id = ?", (path,))
        self.connection.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        if symbol_ids:
            placeholders = ",".join("?" for _ in symbol_ids)
            self.connection.execute(f"DELETE FROM relations WHERE source_type = 'symbol' AND source_id IN ({placeholders})", symbol_ids)
            self.connection.execute(f"DELETE FROM relations WHERE target_type = 'symbol' AND target_id IN ({placeholders})", symbol_ids)
            self.connection.execute(
                f"DELETE FROM relations WHERE target_type = 'resolved_symbol' AND target_id IN ({placeholders})",
                symbol_ids,
            )
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
