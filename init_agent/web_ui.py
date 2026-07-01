"""Read-only local web UI for observing init-agent metadata."""

from __future__ import annotations

import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .utils import db_path


def build_web_snapshot(root: Path, limit: int = 25) -> dict[str, Any]:
    """Return a compact read-only snapshot of local init-agent metadata."""
    bounded_limit = max(1, min(int(limit), 100))
    database = db_path(root)
    project = {"name": root.name, "root": str(root), "database": str(database), "initialized": database.exists()}
    if not database.exists():
        return {
            "project": project,
            "counts": {},
            "recent_memory": [],
            "recent_feedback": [],
            "open_tasks": [],
            "recent_plans": [],
            "file_activity": [],
            "warnings": ["init-agent index not found. Run: init-agent run --overview --markdown"],
        }

    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        counts = _counts(conn)
        recent_memory = _recent_memory(conn, bounded_limit)
        recent_feedback = _recent_feedback(conn, bounded_limit)
        open_tasks = _open_tasks(conn, bounded_limit)
        recent_plans = _recent_plans(conn, bounded_limit)
        file_activity = _file_activity(conn, bounded_limit)

    return {
        "project": project,
        "counts": counts,
        "recent_memory": recent_memory,
        "recent_feedback": recent_feedback,
        "open_tasks": open_tasks,
        "recent_plans": recent_plans,
        "file_activity": file_activity,
        "warnings": [],
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
        ("plans", "Plans"),
        ("files", "Files"),
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
            '<div class="overview-grid">',
            _compact_list("Open Tasks", ["id", "status", "topic", "title", "remaining"], snapshot.get("open_tasks") or []),
            _compact_list("Recent Plans", ["id", "status", "query", "summary"], snapshot.get("recent_plans") or []),
            _compact_list("Top File Activity", ["path", "memory", "feedback", "plan_events", "total"], snapshot.get("file_activity") or []),
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
            '<section class="tab-panel" data-tab="plans">',
            _table_block(
                "Recent Reading Plans",
                ["id", "status", "read_budget", "query", "summary", "created_at"],
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
            "</main>",
            "<script>",
            _JS,
            "</script>",
            "</body>",
            "</html>",
        ]
    )


def serve_web_ui(root: Path, host: str = "127.0.0.1", port: int = 8765, limit: int = 25) -> None:
    """Serve the local read-only dashboard until interrupted."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            if parsed.path == "/api/snapshot":
                payload = json.dumps(build_web_snapshot(root, limit=limit), indent=2, sort_keys=True).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
                return
            if parsed.path not in {"", "/"}:
                self._send(404, "text/plain; charset=utf-8", b"not found\n")
                return
            payload = render_dashboard_html(build_web_snapshot(root, limit=limit)).encode("utf-8")
            self._send(200, "text/html; charset=utf-8", payload)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, content_type: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer((host, int(port)), Handler)
    print(f"Init Agent web UI: http://{host}:{port}/")
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
    ]
    return {table: _table_count(conn, table) for table in tables}


def _recent_memory(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
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
    return [
        {
            "id": row["id"],
            "path": row["path"],
            "scope": row["scope"] or "file",
            "topic": row["topic"] or "",
            "query": row["query"] or "",
            "note": row["note"],
            "evidence": row["evidence"] or "",
            "source": row["source"],
            "stale": _memory_stale(conn, row["path"], row["file_sha256"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


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
    rows = conn.execute(
        """
        SELECT id, query, read_budget, summary, finished_at, created_at
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
        for row in conn.execute(f"SELECT {column} AS path, COUNT(*) AS count FROM {table} WHERE {column} != '' GROUP BY {column}"):
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


def _memory_stale(conn: sqlite3.Connection, path: str, file_sha256: str | None) -> bool | None:
    if not path or not file_sha256:
        return None
    row = conn.execute("SELECT sha256 FROM files WHERE path = ?", (path,)).fetchone()
    if row is None:
        return True
    return str(row["sha256"] or "") != str(file_sha256 or "")


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if not _has_table(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return row is not None


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
    ]
    cards = "".join(
        f'<div><strong>{value}</strong><span>{_e(key.replace("_", " "))}</span></div>'
        for key in priority
        if (value := counts.get(key)) is not None
    )
    return f'<section class="metrics">{cards}</section>'


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
  --bg: #f4f6f8;
  --panel: #ffffff;
  --text: #1d2430;
  --muted: #5c6878;
  --line: #d9dee7;
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
  padding: 20px 32px;
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
.layout { max-width: 1380px; margin: 0 auto; padding: 24px 32px 48px; }
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
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.metrics div, .panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.metrics div { padding: 16px; }
.metrics strong { display: block; font-size: 24px; }
.metrics span { color: var(--muted); }
.panel { margin: 18px 0; overflow: hidden; }
.panel h2 { margin: 0; padding: 14px 16px; font-size: 16px; border-bottom: 1px solid var(--line); }
.warning { background: var(--warn); padding-bottom: 8px; }
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}
.compact-panel { margin: 0; }
.compact-list { display: grid; }
.compact-item {
  display: grid;
  gap: 3px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
}
.compact-item:last-child { border-bottom: 0; }
.compact-item strong {
  overflow-wrap: anywhere;
}
.compact-item span {
  color: var(--muted);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.empty {
  margin: 0;
  padding: 14px 16px;
  color: var(--muted);
}
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 860px; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
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
.filter-row.hidden { display: none; }
@media (max-width: 760px) {
  header, .toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .layout { padding: 18px 16px 32px; }
  .search { min-width: 0; }
}
"""


_JS = """
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
