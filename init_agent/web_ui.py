"""Read-only local web UI for observing init-agent metadata."""

from __future__ import annotations

import html
import hashlib
import os
import stat
import time
import ipaddress
import json
import secrets
import socket
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .web_budget import (BoundedHTTPServer, LimitedHeaders, SnapshotCache,
                         MAX_RESPONSE_BYTES, SNAPSHOT_ROWS, SNAPSHOT_SECONDS, SNAPSHOT_STEPS)
from .plan_feedback import scorecard_evidence_confidence
from .memory import _with_staleness
from .trajectory import stored_tool_status
from .repo_files import open_repo_file
from .utils import db_path, safe_print as print


def build_web_snapshot(root: Path, limit: int = 25) -> dict[str, Any]:
    """Return a compact read-only snapshot of local init-agent metadata."""
    bounded_limit = max(1, min(int(limit), 100))
    database = db_path(root)
    project = {"name": root.name, "root": str(root), "database": str(database), "initialized": database.exists()}
    if not database.exists():
        return {
            "project": project,
            "counts": {},
            "scorecard": {},
            "recent_memory": [],
            "recent_feedback": [],
            "open_tasks": [],
            "recent_plans": [],
            "file_activity": [],
            "trajectory_summary": {},
            "trajectory_sessions": [],
            "trajectory_events": [],
            "warnings": ["init-agent index not found. Run: init-agent run --overview --markdown"],
        }

    uri = f"file:{database}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65_536)
        started = time.monotonic()
        steps = 0
        def exhausted():
            nonlocal steps
            steps += 1000
            return int(steps > SNAPSHOT_STEPS or time.monotonic() - started > SNAPSHOT_SECONDS)
        conn.set_progress_handler(exhausted, 1000)
        counts = _counts(conn)
        recent_memory = _recent_memory(conn, bounded_limit, root)
        recent_feedback = _recent_feedback(conn, bounded_limit)
        open_tasks = _open_tasks(conn, bounded_limit)
        recent_plans = _recent_plans(conn, bounded_limit)
        file_activity = _file_activity(conn, bounded_limit)
        scorecard = _scorecard(conn, bounded_limit)
        for table in ("trajectory_events", "trajectory_sessions"):
            if _has_table(conn, table):
                conn.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM main.{table} ORDER BY id DESC LIMIT {SNAPSHOT_ROWS}")
        trajectory_summary = _trajectory_summary(conn)
        trajectory_sessions = _trajectory_sessions(conn, bounded_limit)
        trajectory_events = _trajectory_events(conn, bounded_limit)

    return {
        "project": project,
        "counts": counts,
        "scorecard": scorecard,
        "recent_memory": recent_memory,
        "recent_feedback": recent_feedback,
        "open_tasks": open_tasks,
        "recent_plans": recent_plans,
        "file_activity": file_activity,
        "trajectory_summary": trajectory_summary,
        "trajectory_sessions": trajectory_sessions,
        "trajectory_events": trajectory_events,
        "warnings": ["Table counts are capped at 10,000; a count at the cap is a lower bound.", f"Activity and trajectory use the latest {SNAPSHOT_ROWS} records; scorecard detail is capped at {SNAPSHOT_ROWS} selected records; live hash reads are capped at 8 MiB."],
    }


def render_dashboard_html(snapshot: dict[str, Any]) -> str:
    """Render the local metadata snapshot as a self-contained HTML page."""
    project = snapshot.get("project", {})
    counts = snapshot.get("counts", {})
    title = f"init-agent · {project.get('name') or 'project'}"
    tabs = [
        ("overview", "Overview"),
        ("memory", "Memory"),
        ("feedback", "Feedback"),
        ("tasks", "Tasks"),
        ("scorecard", "Scorecard"),
        ("plans", "Plans"),
        ("files", "Files"),
        ("trajectory", "Trajectory"),
    ]
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_e(title)}</title>",
            "<style>",
            _CSS,
            "</style>",
            "</head>",
            "<body>",
            "<header>",
            "<div>",
            "<p>Local Agent Observatory</p>",
            f"<h1>{_e(project.get('name') or 'Project')}</h1>",
            f"<span>{_e(project.get('root') or '')}</span>",
            "</div>",
            "<nav>",
            '<a href="/">Dashboard</a>',
            '<a href="/api/snapshot">JSON</a>',
            "</nav>",
            "</header>",
            '<main class="layout">',
            _warning_block(snapshot.get("warnings") or []),
            '<section class="toolbar">',
            '<div class="tabs" role="tablist" aria-label="Dashboard sections">',
            "".join(
                f'<button class="tab{" active" if key == "overview" else ""}" data-tab-target="{key}" type="button">{_e(label)}</button>'
                for key, label in tabs
            ),
            "</div>",
            '<label class="search"><span>Search</span><input id="table-search" type="search" placeholder="Filter path, topic, note, query..." autocomplete="off"></label>',
            "</section>",
            '<section class="tab-panel active" data-tab="overview">',
            _counts_block(counts),
            '<div class="overview-grid dashboard-grid">',
            _compact_list("Open Tasks", ["id", "status", "topic", "title", "remaining"], snapshot.get("open_tasks") or []),
            _scorecard_block(snapshot.get("scorecard") or {}),
            _compact_list("Recent Plans", ["id", "status", "query", "summary"], snapshot.get("recent_plans") or []),
            _compact_list("Top File Activity", ["path", "memory", "feedback", "plan_events", "total"], snapshot.get("file_activity") or []),
            _trajectory_block(snapshot.get("trajectory_summary") or {}),
            _compact_list(
                "Recent Trajectory Sessions",
                ["session_id", "status", "model", "event_count", "tool_call_count", "error_count"],
                snapshot.get("trajectory_sessions") or [],
            ),
            "</div>",
            "</section>",
            '<section class="tab-panel" data-tab="memory">',
            _table_block(
                "Recent Memory",
                ["id", "scope", "path", "topic", "evidence", "stale", "note"],
                snapshot.get("recent_memory") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="feedback">',
            _table_block(
                "Recent Feedback",
                ["id", "rating", "path", "query", "source", "reason"],
                snapshot.get("recent_feedback") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="tasks">',
            _table_block(
                "Open Tasks",
                ["id", "status", "topic", "title", "summary", "files", "remaining"],
                snapshot.get("open_tasks") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="scorecard">',
            _scorecard_block(snapshot.get("scorecard") or {}),
            _table_block(
                "Included Plans",
                ["id", "kind", "evaluable", "top1_hit", "top3_hit", "top5_hit", "first_useful_read_position", "missing_count", "extra_read_count", "query"],
                (snapshot.get("scorecard") or {}).get("plans") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="plans">',
            _table_block(
                "Recent Reading Plans",
                ["id", "status", "kind", "read_budget", "query", "summary", "created_at"],
                snapshot.get("recent_plans") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="files">',
            _table_block(
                "File Activity",
                ["path", "memory", "feedback", "plan_events", "total"],
                snapshot.get("file_activity") or [],
            ),
            "</section>",
            '<section class="tab-panel" data-tab="trajectory">',
            _trajectory_block(snapshot.get("trajectory_summary") or {}),
            _table_block(
                "Trajectory Sessions",
                ["session_id", "status", "source", "model", "event_count", "tool_call_count", "error_count", "subagent_count", "started_at", "ended_at"],
                snapshot.get("trajectory_sessions") or [],
            ),
            _table_block(
                "Recent Observable Events",
                ["id", "session_id", "event_name", "tool_name", "status", "duration_ms", "paths", "command_name", "created_at"],
                snapshot.get("trajectory_events") or [],
            ),
            "</section>",
            "</main>",
            "<script>",
            _JS,
            "</script>",
            "</body>",
            "</html>",
        ]
    )


def _snapshot_payloads(root: Path, limit: int):
    snapshot = build_web_snapshot(root, limit=limit)
    payload = bytearray()
    for chunk in json.JSONEncoder(indent=2, sort_keys=True).iterencode(snapshot):
        block = chunk.encode("utf-8")
        if len(payload) + len(block) > MAX_RESPONSE_BYTES:
            raise ValueError("snapshot response budget exceeded")
        payload.extend(block)
    html_payload = render_dashboard_html(snapshot).encode("utf-8")
    if len(html_payload) > MAX_RESPONSE_BYTES:
        raise ValueError("dashboard response budget exceeded")
    return bytes(payload), html_payload


def serve_web_ui(root: Path, host: str = "127.0.0.1", port: int = 8765, limit: int = 25) -> None:
    """Serve the local read-only dashboard until interrupted."""
    bind_host = "127.0.0.1" if host.lower() == "localhost" else host
    try:
        address = ipaddress.ip_address(bind_host)
    except ValueError:
        raise ValueError("web host must be localhost or a loopback IP address") from None
    if not address.is_loopback:
        raise ValueError("web dashboard is local-only; use a loopback IP address")
    bind_host = str(address)
    authority_host = f"[{bind_host}]" if address.version == 6 else bind_host

    capability = secrets.token_urlsafe(32)
    cache = SnapshotCache(lambda: _snapshot_payloads(root, limit))

    class Handler(BaseHTTPRequestHandler):
        def parse_request(self):
            if len(self.raw_requestline) > 4096:
                self.requestline = ""
                self.request_version = "HTTP/1.0"
                self.command = ""
                self.send_error(414)
                return False
            self.rfile = LimitedHeaders(self.rfile)
            return super().parse_request()

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            authorities = {f"{authority_host}:{server.server_port}", f"localhost:{server.server_port}"}
            if server.server_port == 80:
                authorities.update({authority_host, "localhost"})
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            if (
                len(hosts) != 1 or hosts[0].lower() not in authorities
                or len(origins) > 1
                or (origins and origins[0].lower() != f"http://{hosts[0].lower()}")
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                self._send(403, "text/plain; charset=utf-8", b"local requests only\n")
                return
            parsed = urlparse(self.path)
            credentials = self.headers.get_all("Authorization", [])
            # The public bootstrap contains no repository data or capability.
            if parsed.path == "/" and not credentials:
                self._send(200, "text/html; charset=utf-8", _BOOTSTRAP.encode("utf-8"))
                return
            if (len(credentials) != 1 or not secrets.compare_digest(
                credentials[0].encode("utf-8"), f"Bearer {capability}".encode("ascii")
            )):
                self._send(401, "text/plain; charset=utf-8", b"launch capability required\n")
                return
            if parsed.path not in {"", "/", "/api/snapshot"}:
                self._send(404, "text/plain; charset=utf-8", b"not found\n")
                return
            try:
                json_payload, html_payload = cache.get()
            except (sqlite3.Error, OSError, ValueError, RecursionError):
                self._send(503, "text/plain; charset=utf-8", b"snapshot unavailable or work budget exceeded\n")
                return
            if parsed.path == "/api/snapshot":
                payload = json_payload
                self._send(200, "application/json; charset=utf-8", payload)
                return
            payload = html_payload
            self._send(200, "text/html; charset=utf-8", payload)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, content_type: str, payload: bytes) -> None:
            if len(payload) > MAX_RESPONSE_BYTES:
                status, content_type, payload = 503, "text/plain; charset=utf-8", b"snapshot response budget exceeded\n"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def end_headers(self):
            # Apply response protections to parser errors as well as normal routes.
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

    class LocalServer(BoundedHTTPServer):
        address_family = socket.AF_INET6 if address.version == 6 else socket.AF_INET

    server = LocalServer((bind_host, int(port)), Handler)
    print(f"Init Agent web UI: http://{authority_host}:{server.server_port}/#token={capability}")
    print("This private link grants dashboard access for this launch. Do not share it.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "files",
        "symbols",
        "relations",
        "orientation_feedback",
        "agent_notes",
        "agent_tasks",
        "reading_plans",
        "reading_plan_events",
        "trajectory_sessions",
        "trajectory_events",
    ]
    return {table: _table_count(conn, table) for table in tables}


def _bounded_staleness(root: Path, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hashes = {}
    limited = set()
    remaining = 8 * 1024 * 1024
    deadline = time.monotonic() + SNAPSHOT_SECONDS
    for note in notes:
        path = str(note["path"])
        if note.get("scope") == "repo" or path in hashes:
            continue
        hashes[path] = None
        try:
            if time.monotonic() >= deadline or remaining <= 0:
                limited.add(path)
                continue
            with open_repo_file(root, path) as handle:
                info = os.fstat(handle.fileno())
                allowance = min(remaining, 256 * 1024)
                if not stat.S_ISREG(info.st_mode):
                    continue
                if info.st_size > allowance:
                    limited.add(path)
                    continue
                data = handle.read(allowance + 1)
                remaining -= len(data)
                if len(data) > allowance or time.monotonic() >= deadline:
                    limited.add(path)
                    continue
                hashes[path] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError, RuntimeError):
            continue
    result = []
    for note in notes:
        item = _with_staleness(note, hashes)
        if str(note["path"]) in limited and note.get("scope") != "repo":
            item.update(stale=None, stale_reason="live hash work budget exceeded")
        result.append(item)
    return result


def _recent_memory(conn: sqlite3.Connection, limit: int, root: Path) -> list[dict[str, Any]]:
    if not _has_table(conn, "agent_notes"):
        return []
    rows = conn.execute(
        """
        SELECT id, path, scope, topic, query, note, evidence, source, file_sha256, created_at
        FROM agent_notes
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    notes = [
        {
            "id": row["id"],
            "path": row["path"],
            "scope": row["scope"] or "file",
            "topic": row["topic"] or "",
            "query": row["query"] or "",
            "note": row["note"],
            "evidence": row["evidence"] or "",
            "source": row["source"],
            "file_sha256": row["file_sha256"] or "",
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return _bounded_staleness(root, notes)


def _recent_feedback(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not _has_table(conn, "orientation_feedback"):
        return []
    rows = conn.execute(
        """
        SELECT id, query, path, rating, reason, source, created_at
        FROM orientation_feedback
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _open_tasks(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not _has_table(conn, "agent_tasks"):
        return []
    rows = conn.execute(
        """
        SELECT id, title, status, topic, summary, files_json, remaining_json, updated_at
        FROM agent_tasks
        WHERE status != 'done'
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    tasks = []
    for row in rows:
        tasks.append(
            {
                "id": row["id"],
                "title": row["title"],
                "status": row["status"],
                "topic": row["topic"] or "",
                "summary": row["summary"] or "",
                "files": _json_list(row["files_json"]),
                "remaining": "; ".join(_json_list(row["remaining_json"])),
                "updated_at": row["updated_at"],
            }
        )
    return tasks


def _recent_plans(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not _has_table(conn, "reading_plans"):
        return []
    kind_select = "kind" if _has_column(conn, "reading_plans", "kind") else "'real' AS kind"
    rows = conn.execute(
        f"""
        SELECT id, query, read_budget, {kind_select}, summary, finished_at, created_at
        FROM reading_plans
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "query": row["query"],
            "read_budget": row["read_budget"],
            "kind": row["kind"] or "real",
            "summary": row["summary"] or "",
            "status": "finished" if row["finished_at"] else "open",
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _file_activity(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {}
    for table, column, key in [
        ("agent_notes", "path", "memory"),
        ("orientation_feedback", "path", "feedback"),
        ("reading_plan_events", "path", "plan_events"),
    ]:
        if not _has_table(conn, table):
            continue
        for row in conn.execute(f"SELECT {column} AS path, COUNT(*) AS count FROM (SELECT {column} FROM {table} ORDER BY id DESC LIMIT {SNAPSHOT_ROWS}) WHERE {column} != '' GROUP BY {column}"):
            path = str(row["path"])
            item = counts.setdefault(path, {"memory": 0, "feedback": 0, "plan_events": 0})
            item[key] = int(row["count"])
    activity = [
        {
            "path": path,
            "memory": values["memory"],
            "feedback": values["feedback"],
            "plan_events": values["plan_events"],
            "total": values["memory"] + values["feedback"] + values["plan_events"],
        }
        for path, values in counts.items()
    ]
    activity.sort(key=lambda item: (-item["total"], item["path"]))
    return activity[:limit]


def _trajectory_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    if not (_has_table(conn, "trajectory_sessions") and _has_table(conn, "trajectory_events")):
        return {}
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM trajectory_sessions) AS session_count,
            COUNT(*) AS event_count,
            SUM(CASE WHEN event_name = 'PostToolUse' THEN 1 ELSE 0 END) AS tool_call_count,
            SUM(CASE WHEN event_name = 'PostToolUse' AND status = 'error' THEN 1 ELSE 0 END) AS error_count,
            SUM(CASE WHEN event_name = 'SubagentStart' THEN 1 ELSE 0 END) AS subagent_count,
            AVG(CASE WHEN event_name = 'PostToolUse' THEN duration_ms END) AS average_tool_duration_ms
        FROM trajectory_events
        """
    ).fetchone()
    durations = sorted(
        int(item["duration_ms"])
        for item in conn.execute(
            "SELECT duration_ms FROM trajectory_events WHERE event_name = 'PostToolUse' AND duration_ms IS NOT NULL"
        )
    )
    p95_index = max(0, min(len(durations) - 1, int((len(durations) - 1) * 0.95))) if durations else 0
    top_tools = [
        {"tool": str(item["tool_name"] or "unknown"), "count": int(item["count"])}
        for item in conn.execute(
            """
            SELECT tool_name, COUNT(*) AS count
            FROM trajectory_events
            WHERE event_name = 'PostToolUse'
            GROUP BY tool_name
            ORDER BY count DESC, tool_name
            LIMIT 5
            """
        )
    ]
    outcomes = {"success": 0, "error": 0, "unknown": 0}
    for event in conn.execute("SELECT metadata_json FROM trajectory_events WHERE event_name = 'PostToolUse'"):
        outcomes[stored_tool_status(event["metadata_json"])] += 1
    completed = sum(outcomes.values())
    return {
        "session_count": int(row["session_count"] or 0),
        "event_count": int(row["event_count"] or 0),
        "tool_call_count": int(row["tool_call_count"] or 0),
        "error_count": outcomes["error"],
        "unknown_outcome_count": outcomes["unknown"],
        "outcome_coverage_percent": round(100 * (completed - outcomes["unknown"]) / completed, 1) if completed else None,
        "subagent_count": int(row["subagent_count"] or 0),
        "average_tool_duration_ms": round(float(row["average_tool_duration_ms"] or 0), 1),
        "p95_tool_duration_ms": durations[p95_index] if durations else 0,
        "top_tools": top_tools,
        "duration_quality": "observed hook interval",
    }


def _trajectory_sessions(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not (_has_table(conn, "trajectory_sessions") and _has_table(conn, "trajectory_events")):
        return []
    rows = conn.execute(
        """
        SELECT
            sessions.id,
            sessions.external_session_id AS session_id,
            sessions.source,
            sessions.model,
            sessions.cwd,
            sessions.started_at,
            sessions.ended_at,
            sessions.end_reason,
            COUNT(events.id) AS event_count,
            SUM(CASE WHEN events.event_name = 'PostToolUse' THEN 1 ELSE 0 END) AS tool_call_count,
            SUM(CASE WHEN events.event_name = 'PostToolUse' AND events.status = 'error' THEN 1 ELSE 0 END) AS error_count,
            SUM(CASE WHEN events.event_name = 'SubagentStart' THEN 1 ELSE 0 END) AS subagent_count
        FROM trajectory_sessions AS sessions
        LEFT JOIN trajectory_events AS events ON events.session_id = sessions.id
        GROUP BY sessions.id
        ORDER BY sessions.last_event_at DESC, sessions.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            **dict(row),
            "status": "finished" if row["ended_at"] else "active",
            "event_count": int(row["event_count"] or 0),
            "tool_call_count": int(row["tool_call_count"] or 0),
            "error_count": int(row["error_count"] or 0),
            "subagent_count": int(row["subagent_count"] or 0),
        }
        for row in rows
    ]


def _trajectory_events(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    if not (_has_table(conn, "trajectory_sessions") and _has_table(conn, "trajectory_events")):
        return []
    rows = conn.execute(
        """
        SELECT
            events.id,
            sessions.external_session_id AS session_id,
            events.turn_id,
            events.event_name,
            events.tool_name,
            events.agent_id,
            events.agent_type,
            events.status,
            events.duration_ms,
            events.metadata_json,
            events.created_at
        FROM trajectory_events AS events
        JOIN trajectory_sessions AS sessions ON sessions.id = events.session_id
        ORDER BY events.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        if item["event_name"] == "PostToolUse":
            item["status"] = stored_tool_status(item["metadata_json"])
        try:
            metadata = json.loads(str(item.pop("metadata_json") or "{}"))
        except json.JSONDecodeError:
            metadata = {}
        tool_input = metadata.get("tool_input") if isinstance(metadata.get("tool_input"), dict) else {}
        item["paths"] = tool_input.get("paths") or []
        item["command_name"] = tool_input.get("command_name") or ""
        events.append(item)
    return events


def _scorecard(conn: sqlite3.Connection, limit: int) -> dict[str, Any]:
    if not (_has_table(conn, "reading_plans") and _has_table(conn, "reading_plan_items") and _has_table(conn, "reading_plan_events")):
        return {}
    kind_column = _has_column(conn, "reading_plans", "kind")
    kind_select = "kind" if kind_column else "'' AS kind"
    plans = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT id, query, read_budget, {kind_select}, summary, finished_at, created_at
            FROM reading_plans
            WHERE finished_at IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    ]
    excluded_kinds = {"smoke", "experiment", "planning", "diagnostic", "docs"}
    for plan in plans:
        plan["effective_kind"] = _effective_plan_kind(plan)
    included = [plan for plan in plans if plan["effective_kind"] not in excluded_kinds]
    excluded = [plan for plan in plans if plan["effective_kind"] in excluded_kinds]
    included_ids = {int(plan["id"]) for plan in included}
    if not plans:
        return {
            "scorecard_limit": limit,
            "scorecard_included_plan_count": 0,
            "scorecard_excluded_plan_count": 0,
            "scorecard_evaluable_plan_count": 0,
            "scorecard_not_evaluable_plan_count": 0,
            "plans": [],
        }
    has_ranking_diagnostics = _has_column(conn, "reading_plan_items", "signal_contributions_json")
    diagnostic_select = (
        "base_rank, signal_contributions_json"
        if has_ranking_diagnostics
        else "0 AS base_rank, '{}' AS signal_contributions_json"
    )
    plan_ids = sorted(included_ids)
    placeholders = ",".join("?" for _ in plan_ids) or "NULL"
    item_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT plan_id, path, rank, {diagnostic_select} FROM reading_plan_items WHERE plan_id IN ({placeholders}) LIMIT {SNAPSHOT_ROWS}", plan_ids
        ).fetchall()
    ]
    event_rows = [dict(row) for row in conn.execute(f"SELECT plan_id, event, path FROM reading_plan_events WHERE plan_id IN ({placeholders}) ORDER BY id DESC LIMIT {SNAPSHOT_ROWS}", plan_ids).fetchall()]
    event_rows.reverse()
    rank_by_plan_path = {(int(row["plan_id"]), str(row["path"])): int(row["rank"] or 0) for row in item_rows}
    item_by_plan_path = {(int(row["plan_id"]), str(row["path"])): row for row in item_rows}
    planned = {}
    for row in item_rows:
        planned.setdefault(int(row["plan_id"]), set()).add(str(row["path"]))
    events = {}
    for row in event_rows:
        plan_id = int(row["plan_id"])
        if plan_id not in included_ids:
            continue
        events.setdefault(plan_id, {}).setdefault(str(row["event"]), []).append(str(row["path"]))
    plan_rows = []
    top_hits = {1: 0, 3: 0, 5: 0}
    evaluable_count = 0
    first_positions = []
    missing_rates = []
    noise_rates = []
    extra_reads = []
    read_counts = []
    outcome_coverages = []
    verified_coverages = []
    base_rank_lifts = []
    signal_lifts = {"memory": [], "feedback": [], "tags": []}
    explicitly_tracked_plans = 0
    for plan in included:
        plan_id = int(plan["id"])
        by_event = events.get(plan_id, {})
        useful = _unique(by_event.get("useful", []))
        central = _unique(by_event.get("central", []))
        support = _unique(by_event.get("support", []))
        created = _unique(by_event.get("created", []))
        verification = _unique(by_event.get("verification", []))
        missing = _unique(by_event.get("missing", []))
        noisy = _unique(by_event.get("noisy", []))
        opened = _unique(by_event.get("opened", []))
        verified = _unique(by_event.get("verified", []))
        read = _unique([*by_event.get("opened", []), *by_event.get("read", [])])
        expected = _unique([*(central or useful), *missing])
        evaluable = bool(expected or noisy)
        if evaluable:
            evaluable_count += 1
        for rank in (1, 3, 5):
            if expected and any(0 < rank_by_plan_path.get((plan_id, path), 0) <= rank for path in expected):
                top_hits[rank] += 1
        first_position = _first_matching_position(read, expected)
        if first_position:
            first_positions.append(first_position)
        if expected:
            missing_rates.append(len(missing) / len(expected))
        if planned.get(plan_id):
            noise_rates.append(len(noisy) / len(planned[plan_id]))
        orientation_read = read[:first_position] if first_position else read
        extra_count = len([path for path in orientation_read if path not in planned.get(plan_id, set())])
        extra_reads.append(extra_count)
        read_counts.append(len(read))
        if opened:
            explicitly_tracked_plans += 1
        classified = set([*useful, *central, *support, *created, *verification, *noisy, *missing])
        outcome_coverage = len(set(read).intersection(classified)) / len(read) if read else None
        verified_coverage = len(set(read).intersection(verified)) / len(read) if read else None
        if outcome_coverage is not None:
            outcome_coverages.append(outcome_coverage)
        if verified_coverage is not None:
            verified_coverages.append(verified_coverage)
        for path in central or useful:
            item = item_by_plan_path.get((plan_id, path))
            if not item:
                continue
            rank = int(item.get("rank") or 0)
            base_rank = int(item.get("base_rank") or 0)
            if rank and base_rank:
                base_rank_lifts.append(base_rank - rank)
            try:
                contributions = json.loads(item.get("signal_contributions_json") or "{}")
            except json.JSONDecodeError:
                contributions = {}
            scores = dict(contributions.get("scores") or {})
            lifts = dict(contributions.get("signal_rank_lift") or {})
            for signal in signal_lifts:
                lift = int(lifts.get(signal) or 0)
                if abs(float(scores.get(signal) or 0.0)) > 0.0 or lift != 0:
                    signal_lifts[signal].append(lift)
        plan_rows.append(
            {
                "id": plan_id,
                "query": str(plan["query"]),
                "kind": str(plan["effective_kind"]),
                "evaluable": evaluable,
                "top1_hit": bool(expected and any(0 < rank_by_plan_path.get((plan_id, path), 0) <= 1 for path in expected)),
                "top3_hit": bool(expected and any(0 < rank_by_plan_path.get((plan_id, path), 0) <= 3 for path in expected)),
                "top5_hit": bool(expected and any(0 < rank_by_plan_path.get((plan_id, path), 0) <= 5 for path in expected)),
                "first_useful_read_position": first_position,
                "central_count": len(central),
                "support_count": len(support),
                "created_count": len(created),
                "verification_count": len(verification),
                "missing_count": len(missing),
                "noisy_count": len(noisy),
                "extra_read_count": extra_count,
                "explicit_read_tracking": bool(opened),
                "read_outcome_coverage": outcome_coverage,
                "verified_read_coverage": verified_coverage,
            }
        )
    excluded_by_kind = {}
    for plan in excluded:
        kind = str(plan["effective_kind"])
        excluded_by_kind[kind] = excluded_by_kind.get(kind, 0) + 1
    explicit_tracking_rate = explicitly_tracked_plans / len(included) if included else 0.0
    outcome_coverage = _avg(outcome_coverages)
    confidence, confidence_reasons = scorecard_evidence_confidence(
        evaluable_count,
        explicit_tracking_rate,
        outcome_coverage,
    )
    return {
        "scorecard_limit": limit,
        "scorecard_included_plan_count": len(included),
        "scorecard_excluded_plan_count": len(excluded),
        "scorecard_excluded_by_kind": excluded_by_kind,
        "scorecard_evaluable_plan_count": evaluable_count,
        "scorecard_not_evaluable_plan_count": len(included) - evaluable_count,
        "top1_hit_rate": _rate(top_hits[1], evaluable_count),
        "top3_hit_rate": _rate(top_hits[3], evaluable_count),
        "top5_hit_rate": _rate(top_hits[5], evaluable_count),
        "average_first_useful_read_position": _avg(first_positions),
        "average_base_to_assisted_rank_lift": _avg(base_rank_lifts),
        "signal_impact": {
            signal: {
                "observed_useful_files": len(values),
                "average_rank_lift": _avg(values),
                "promoted": sum(1 for value in values if value > 0),
                "unchanged": sum(1 for value in values if value == 0),
                "demoted": sum(1 for value in values if value < 0),
            }
            for signal, values in signal_lifts.items()
        },
        "average_files_read_per_finished_plan": _avg(read_counts),
        "average_extra_files_read_per_finished_plan": _avg(extra_reads),
        "explicit_read_tracking_rate": explicit_tracking_rate,
        "average_read_outcome_coverage": outcome_coverage,
        "average_verified_read_coverage": _avg(verified_coverages),
        "scorecard_confidence": confidence,
        "scorecard_confidence_reasons": confidence_reasons,
        "missing_rate": _avg(missing_rates),
        "noise_rate": _avg(noise_rates),
        "plans": plan_rows,
    }


def _effective_plan_kind(plan: dict[str, Any]) -> str:
    explicit = str(plan.get("kind") or "").strip()
    if explicit:
        return explicit
    text = f"{plan.get('query') or ''} {plan.get('summary') or ''}".lower()
    if "smoke" in text or "upgrade" in text:
        return "smoke"
    if "experiment" in text or "esperimento" in text or "probe" in text:
        return "experiment"
    if "roadmap" in text or "priorità" in text or "priority" in text:
        return "planning"
    if "diagnostic" in text or "exploratory" in text:
        return "diagnostic"
    return "real"


def _unique(paths: list[str]) -> list[str]:
    result = []
    seen = set()
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _first_matching_position(read_paths: list[str], expected_paths: list[str]) -> int | None:
    expected = set(expected_paths)
    if not expected:
        return None
    for index, path in enumerate(read_paths, start=1):
        if path in expected:
            return index
    return None


def _rate(count: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(count / denominator, 4)


def _avg(values: list[float] | list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if not _has_table(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM {table} LIMIT 10000)").fetchone()[0])


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _has_table(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return column in {str(row["name"]) for row in rows}


def _percent(value: Any) -> str:
    try:
        return f"{100 * float(value):.0f}%"
    except (TypeError, ValueError):
        return "0%"


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _warning_block(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{_e(item)}</li>" for item in warnings)
    return f'<section class="panel warning"><h2>Warnings</h2><ul>{items}</ul></section>'


def _counts_block(counts: dict[str, int]) -> str:
    if not counts:
        return '<section class="metrics"></section>'
    priority = [
        "files",
        "symbols",
        "relations",
        "orientation_feedback",
        "agent_notes",
        "agent_tasks",
        "reading_plans",
        "reading_plan_events",
        "trajectory_sessions",
        "trajectory_events",
    ]
    cards = "".join(
        f'<div><strong>{value}</strong><span>{_e(key.replace("_", " "))}</span></div>'
        for key in priority
        if (value := counts.get(key)) is not None
    )
    return f'<section class="metrics">{cards}</section>'


def _scorecard_block(scorecard: dict[str, Any]) -> str:
    if not scorecard:
        return '<section class="panel compact-panel"><h2>Orientation Scorecard</h2><p class="empty">No scorecard data.</p></section>'
    metrics = [
        ("Included", scorecard.get("scorecard_included_plan_count", 0)),
        ("Evaluable", scorecard.get("scorecard_evaluable_plan_count", 0)),
        ("Top-1", _percent(scorecard.get("top1_hit_rate", 0))),
        ("Top-3", _percent(scorecard.get("top3_hit_rate", 0))),
        ("Top-5", _percent(scorecard.get("top5_hit_rate", 0))),
        ("Evidence", scorecard.get("scorecard_confidence", "low")),
        ("Tracked", _percent(scorecard.get("explicit_read_tracking_rate", 0))),
        ("Outcomes", _percent(scorecard.get("average_read_outcome_coverage", 0))),
        ("Missing", _percent(scorecard.get("missing_rate", 0))),
        ("Noise", _percent(scorecard.get("noise_rate", 0))),
        ("First central", scorecard.get("average_first_useful_read_position", 0)),
        ("Assisted lift", scorecard.get("average_base_to_assisted_rank_lift", 0)),
    ]
    cards = "".join(f"<div><strong>{_e(value)}</strong><span>{_e(label)}</span></div>" for label, value in metrics)
    excluded = scorecard.get("scorecard_excluded_by_kind") or {}
    excluded_text = ", ".join(f"{kind}: {count}" for kind, count in excluded.items()) or "none"
    confidence_text = "; ".join(scorecard.get("scorecard_confidence_reasons") or []) or "insufficient evidence"
    signal_text = "; ".join(
        f"{signal}: {item.get('average_rank_lift', 0)} avg lift over {item.get('observed_useful_files', 0)} central/useful files"
        for signal, item in (scorecard.get("signal_impact") or {}).items()
    ) or "no assisted-ranking observations yet"
    return (
        '<section class="panel scorecard-panel">'
        "<h2>Orientation Scorecard</h2>"
        f'<div class="metrics mini-metrics">{cards}</div>'
        f'<p class="muted">Evidence quality: {_e(confidence_text)}</p>'
        f'<p class="muted">Ranking signals: {_e(signal_text)}</p>'
        f'<p class="muted">Excluded from default scorecard: {_e(excluded_text)}</p>'
        "</section>"
    )


def _trajectory_block(summary: dict[str, Any]) -> str:
    if not summary:
        return (
            '<section class="panel compact-panel"><h2>Observable Trajectory</h2>'
            '<p class="empty">No trajectory data. Optional Codex hooks can record redacted local events.</p></section>'
        )
    metrics = [
        ("Sessions", summary.get("session_count", 0)),
        ("Events", summary.get("event_count", 0)),
        ("Tool calls", summary.get("tool_call_count", 0)),
        ("Errors", summary.get("error_count", 0)),
        ("Subagents", summary.get("subagent_count", 0)),
        ("Avg tool", f"{summary.get('average_tool_duration_ms', 0)} ms"),
        ("P95 tool", f"{summary.get('p95_tool_duration_ms', 0)} ms"),
    ]
    cards = "".join(f"<div><strong>{_e(value)}</strong><span>{_e(label)}</span></div>" for label, value in metrics)
    top_tools = ", ".join(
        f"{item.get('tool', 'unknown')}: {item.get('count', 0)}" for item in summary.get("top_tools") or []
    ) or "none"
    coverage = summary.get("outcome_coverage_percent")
    coverage_label = f"{coverage}%" if coverage is not None else "n/a"
    return (
        '<section class="panel trajectory-panel">'
        "<h2>Observable Trajectory</h2>"
        f'<div class="metrics mini-metrics">{cards}</div>'
        f'<p class="muted">Top tools: {_e(top_tools)}</p>'
        f'<p class="muted">Unknown outcomes: {_e(summary.get("unknown_outcome_count", 0))}. Outcome coverage: {_e(coverage_label)}.</p>'
        f'<p class="muted">Timing: {_e(summary.get("duration_quality", "unknown"))}. Payloads remain redacted metadata.</p>'
        "</section>"
    )


def _compact_list(title: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        body = '<p class="empty">No data.</p>'
    else:
        body = "".join(_compact_item(columns, row) for row in rows[:8])
    return f'<section class="panel compact-panel"><h2>{_e(title)}</h2><div class="compact-list">{body}</div></section>'


def _compact_item(columns: list[str], row: dict[str, Any]) -> str:
    title_key = "path" if "path" in row else "title" if "title" in row else "query"
    title = _format_cell(row.get(title_key) or row.get("id") or "")
    meta = [
        f"{column}: {_format_cell(row.get(column))}"
        for column in columns
        if column != title_key and row.get(column) not in (None, "", [])
    ]
    search = _row_search(row)
    return (
        f'<article class="compact-item filter-row" data-search="{_e(search)}">'
        f'<strong>{_e(title)}</strong>'
        f'<span>{_e(" · ".join(meta[:4]))}</span>'
        "</article>"
    )


def _table_block(title: str, columns: list[str], rows: list[dict[str, Any]]) -> str:
    headers = "".join(f"<th>{_e(column.replace('_', ' ').title())}</th>" for column in columns)
    if not rows:
        body = f'<tr><td colspan="{len(columns)}">No data.</td></tr>'
    else:
        body = "".join(
            f'<tr class="filter-row" data-search="{_e(_row_search(row))}">'
            + "".join(f"<td>{_cell_html(column, row.get(column))}</td>" for column in columns)
            + "</tr>"
            for row in rows
        )
    return f'<section class="panel"><h2>{_e(title)}</h2><div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div></section>'


def _cell_html(column: str, value: Any) -> str:
    text = _format_cell(value)
    if column in {"note", "reason", "summary", "query", "remaining", "files"}:
        return f'<span class="clamp" title="{_e(text)}">{_e(text)}</span>'
    if column in {"status", "rating", "stale", "evidence", "scope"} and text:
        normalized = text.lower().replace(" ", "-")
        return f'<span class="badge badge-{_e(normalized)}">{_e(text)}</span>'
    if column == "path":
        return f'<code>{_e(text)}</code>'
    return _e(text)


def _format_cell(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _row_search(row: dict[str, Any]) -> str:
    return " ".join(_format_cell(value).lower() for value in row.values())


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


_CSS = """
:root {
  color-scheme: light;
  --bg: #f5f7fa;
  --panel: #ffffff;
  --text: #1d2430;
  --muted: #5c6878;
  --muted-strong: #465365;
  --line: #d9dee7;
  --line-soft: #e8ecf2;
  --accent: #1769aa;
  --accent-soft: #e8f2fb;
  --ok: #176b43;
  --bad: #9d2b2b;
  --warn: #fff7db;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 32px;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  position: sticky;
  top: 0;
  z-index: 10;
}
header p, header span { margin: 0; color: var(--muted); }
h1 { margin: 2px 0 4px; font-size: 28px; }
nav { display: flex; gap: 12px; align-items: center; }
a { color: var(--accent); text-decoration: none; }
.layout {
  width: min(100% - 48px, 1640px);
  margin: 0 auto;
  padding: 24px 0 48px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}
.tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.tab {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  padding: 8px 12px;
}
.tab.active {
  border-color: color-mix(in srgb, var(--accent) 46%, var(--line));
  background: var(--accent-soft);
  color: var(--accent);
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  min-width: min(420px, 100%);
}
.search input {
  width: 100%;
  min-height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 10px;
  font: inherit;
  color: var(--text);
  background: var(--panel);
}
.tab-panel { display: none; }
.tab-panel.active { display: block; }
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(136px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.metrics div, .panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.metrics div { padding: 14px 16px; }
.metrics strong { display: block; font-size: 24px; }
.metrics span { color: var(--muted); }
.panel {
  margin: 18px 0;
  overflow: hidden;
  min-width: 0;
  box-shadow: 0 1px 2px rgba(18, 27, 38, 0.04);
}
.panel h2 { margin: 0; padding: 14px 16px; font-size: 16px; border-bottom: 1px solid var(--line); }
.warning { background: var(--warn); padding-bottom: 8px; }
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  align-items: start;
}
.dashboard-grid {
  grid-template-columns: minmax(280px, 0.95fr) minmax(320px, 1fr) minmax(380px, 1.2fr);
}
.dashboard-grid .compact-panel:nth-child(4) {
  grid-column: 1 / -1;
}
.compact-panel { margin: 0; }
.compact-list {
  display: grid;
  max-height: 430px;
  overflow: auto;
}
.compact-item {
  display: grid;
  gap: 3px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line-soft);
}
.compact-item:last-child { border-bottom: 0; }
.compact-item strong {
  overflow-wrap: anywhere;
  line-height: 1.35;
}
.compact-item span {
  color: var(--muted);
  font-size: 13px;
  overflow-wrap: anywhere;
  line-height: 1.45;
}
.empty {
  margin: 0;
  padding: 14px 16px;
  color: var(--muted);
}
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 860px; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--line-soft); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
td { max-width: 440px; }
tr:last-child td { border-bottom: 0; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  overflow-wrap: anywhere;
}
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  border-radius: 999px;
  padding: 2px 8px;
  background: #eef1f5;
  color: #344052;
  font-size: 12px;
  white-space: nowrap;
}
.badge-false, .badge-fresh, .badge-useful, .badge-crucial, .badge-done, .badge-finished {
  background: #e8f5ef;
  color: var(--ok);
}
.badge-true, .badge-stale, .badge-noisy, .badge-blocked, .badge-open {
  background: #fff0f0;
  color: var(--bad);
}
.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.scorecard-panel {
  align-self: start;
}
.scorecard-panel .mini-metrics {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 12px;
}
.scorecard-panel .mini-metrics div {
  padding: 12px;
  background: #fbfcfe;
}
.scorecard-panel .mini-metrics strong {
  font-size: 22px;
}
.muted {
  color: var(--muted-strong);
  margin: 0;
  padding: 12px 16px 16px;
  overflow-wrap: anywhere;
}
.filter-row.hidden { display: none; }
@media (max-width: 1180px) {
  .dashboard-grid {
    grid-template-columns: repeat(2, minmax(300px, 1fr));
  }
  .dashboard-grid .compact-panel:nth-child(3),
  .dashboard-grid .compact-panel:nth-child(4) {
    grid-column: auto;
  }
}
@media (max-width: 760px) {
  header, .toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .layout {
    width: min(100% - 28px, 1640px);
    padding: 18px 0 32px;
  }
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .scorecard-panel .mini-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .search { min-width: 0; }
}
"""


_BOOTSTRAP = """<!doctype html>
<html><head><meta charset="utf-8"><title>Init Agent</title></head>
<body><p id="status">Open the private dashboard link printed in your terminal.</p>
<script>
(async () => {
  const incoming = new URLSearchParams(location.hash.slice(1)).get("token");
  history.replaceState(null, "", location.pathname);
  if (incoming) sessionStorage.setItem("init-agent-capability", incoming);
  const token = sessionStorage.getItem("init-agent-capability");
  if (!token) return;
  try {
    const response = await fetch("/", {headers: {Authorization: "Bearer " + token}, cache: "no-store"});
    if (!response.ok) throw new Error("Unauthorized");
    const page = await response.text();
    document.open(); document.write(page); document.close();
  } catch (_) {
    sessionStorage.removeItem("init-agent-capability");
    document.getElementById("status").textContent = "Access expired. Open the current private link from your terminal.";
  }
})();
</script></body></html>
"""


_JS = """
document.querySelector('a[href="/api/snapshot"]')?.addEventListener("click", async (event) => {
  event.preventDefault();
  const token = sessionStorage.getItem("init-agent-capability") || "";
  const response = await fetch("/api/snapshot", {headers: {Authorization: "Bearer " + token}, cache: "no-store"});
  if (!response.ok) { alert("Access expired. Reopen the private dashboard link."); return; }
  const pre = document.createElement("pre");
  pre.textContent = await response.text();
  document.body.replaceChildren(pre);
});

const tabs = Array.from(document.querySelectorAll("[data-tab-target]"));
const panels = Array.from(document.querySelectorAll("[data-tab]"));
const search = document.getElementById("table-search");

function activateTab(name) {
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tabTarget === name));
  panels.forEach((panel) => panel.classList.toggle("active", panel.dataset.tab === name));
  filterRows();
}

function filterRows() {
  const query = (search?.value || "").trim().toLowerCase();
  panels.forEach((panel) => {
    panel.querySelectorAll(".filter-row").forEach((row) => {
      const matches = !query || (row.dataset.search || "").includes(query);
      row.classList.toggle("hidden", !matches);
    });
  });
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tabTarget));
});
search?.addEventListener("input", filterRows);
"""
