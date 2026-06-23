"""Minimal MCP stdio server for init-agent repo tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from io import BufferedIOBase
from pathlib import Path
from typing import Any

from . import __version__
from .agent_tools import (
    repo_entrypoints,
    repo_feedback_add,
    repo_feedback_explain,
    repo_file_notes,
    repo_graph_search,
    repo_memory_add,
    repo_memory_audit,
    repo_memory_delete,
    repo_memory_list,
    repo_memory_search,
    repo_memory_topics,
    repo_memory_update,
    repo_overview,
    repo_related_file,
    repo_session_summary,
    repo_symbol_callers,
)


SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]


ToolHandler = Callable[[Path, dict[str, Any]], dict[str, Any]]
JsonRpcMessage = tuple[dict[str, Any], str]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="init-agent-mcp", description="Run the init-agent MCP stdio server.")
    parser.add_argument("--root", default=".", help="Repository root to serve. Defaults to the current directory.")
    args = parser.parse_args(argv)
    server = InitAgentMcpServer(Path(args.root).resolve())
    return server.serve()


class InitAgentMcpServer:
    """Small JSON-RPC server for MCP clients over stdin/stdout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.debug_log = Path(os.environ["INIT_AGENT_MCP_DEBUG_LOG"]).expanduser() if os.environ.get("INIT_AGENT_MCP_DEBUG_LOG") else None

    def serve(self) -> int:
        self._debug("server_start", {"root": str(self.root), "version": __version__})
        input_stream = sys.stdin.buffer
        output_stream = sys.stdout.buffer
        while True:
            try:
                read_result = _read_message(input_stream)
                if read_result is None:
                    self._debug("server_eof", {})
                    break
                request, response_format = read_result
                self._debug("request", _debug_request_payload(request))
                response = self.handle(request)
            except Exception as exc:
                self._debug("error", {"message": str(exc)})
                response = _error_response(None, -32603, str(exc))
            if response is not None:
                _write_message(response, output_stream, response_format=response_format)
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}

        if not method:
            self._debug("ignored_message", _debug_request_payload(request))
            return None
        if method == "initialize":
            return _result_response(request_id, _initialize_result(params))
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _result_response(request_id, {"tools": _tool_definitions()})
        if method == "tools/call":
            return _result_response(request_id, self._call_tool(params))
        if method == "ping":
            return _result_response(request_id, {})
        return _error_response(request_id, -32601, f"method not found: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        handlers: dict[str, ToolHandler] = {
            "repo_graph_search": _handle_repo_graph_search,
            "repo_entrypoints": _handle_repo_entrypoints,
            "repo_feedback_add": _handle_repo_feedback_add,
            "repo_feedback_explain": _handle_repo_feedback_explain,
            "repo_file_notes": _handle_repo_file_notes,
            "repo_overview": _handle_repo_overview,
            "repo_memory_add": _handle_repo_memory_add,
            "repo_memory_audit": _handle_repo_memory_audit,
            "repo_memory_delete": _handle_repo_memory_delete,
            "repo_memory_list": _handle_repo_memory_list,
            "repo_memory_search": _handle_repo_memory_search,
            "repo_memory_topics": _handle_repo_memory_topics,
            "repo_memory_update": _handle_repo_memory_update,
            "repo_related_file": _handle_repo_related_file,
            "repo_session_summary": _handle_repo_session_summary,
            "repo_symbol_callers": _handle_repo_symbol_callers,
        }
        handler = handlers.get(name)
        if handler is None:
            return _tool_error(f"unknown tool: {name}")
        try:
            result = handler(self.root, arguments)
        except ValueError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            return _tool_error(f"{name} failed: {exc}")
        return _tool_result(result)

    def _debug(self, event: str, payload: dict[str, Any]) -> None:
        if self.debug_log is None:
            return
        try:
            self.debug_log.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": event, **payload}, sort_keys=True) + "\n")
        except OSError:
            pass


def _handle_repo_graph_search(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_graph_search requires query")
    limit = int(arguments.get("limit") or 10)
    return repo_graph_search(root, query, limit=limit, prepare=False)


def _handle_repo_overview(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    return repo_overview(root, prepare=False)


def _handle_repo_entrypoints(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 12)
    return repo_entrypoints(root, prepare=False, limit=limit)


def _handle_repo_related_file(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    if not path:
        raise ValueError("repo_related_file requires path")
    return repo_related_file(root, path, prepare=False)


def _handle_repo_symbol_callers(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    symbol = str(arguments.get("symbol") or "").strip()
    if not symbol:
        raise ValueError("repo_symbol_callers requires symbol")
    limit = int(arguments.get("limit") or 50)
    return repo_symbol_callers(root, symbol, limit=limit, prepare=False)


def _handle_repo_feedback_add(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    path = str(arguments.get("path") or "").strip()
    rating = str(arguments.get("rating") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    source = str(arguments.get("source") or "agent").strip()
    if not query:
        raise ValueError("repo_feedback_add requires query")
    if not path:
        raise ValueError("repo_feedback_add requires path")
    if not rating:
        raise ValueError("repo_feedback_add requires rating")
    return repo_feedback_add(root, query, path, rating, reason=reason, source=source)


def _handle_repo_feedback_explain(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_feedback_explain requires query")
    include_all = bool(arguments.get("include_all") or False)
    return repo_feedback_explain(root, query, include_all=include_all)


def _handle_repo_memory_add(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    note = str(arguments.get("note") or "").strip()
    topic = str(arguments.get("topic") or "").strip()
    query = str(arguments.get("query") or "").strip()
    source = str(arguments.get("source") or "agent").strip()
    evidence = str(arguments.get("evidence") or "read_excerpt").strip()
    scope = str(arguments.get("scope") or "file").strip()
    if scope != "repo" and not path:
        raise ValueError("repo_memory_add requires path for file scope")
    if not note:
        raise ValueError("repo_memory_add requires note")
    return repo_memory_add(root, path, note, topic=topic, query=query, source=source, evidence=evidence, scope=scope)


def _handle_repo_memory_list(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip() or None
    topic = str(arguments.get("topic") or "").strip() or None
    scope = str(arguments.get("scope") or "").strip() or None
    stale_only = bool(arguments.get("stale_only") or False)
    limit = int(arguments.get("limit") or 20)
    return repo_memory_list(root, path=path, topic=topic, scope=scope, stale_only=stale_only, limit=limit)


def _handle_repo_memory_audit(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 100)
    return repo_memory_audit(root, limit=limit)


def _handle_repo_memory_delete(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    note_id = int(arguments.get("id") or 0)
    if note_id <= 0:
        raise ValueError("repo_memory_delete requires positive id")
    return repo_memory_delete(root, note_id)


def _handle_repo_memory_update(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    note_id = int(arguments.get("id") or 0)
    if note_id <= 0:
        raise ValueError("repo_memory_update requires positive id")
    note = str(arguments.get("note")).strip() if "note" in arguments else None
    topic = str(arguments.get("topic")).strip() if "topic" in arguments else None
    query = str(arguments.get("query")).strip() if "query" in arguments else None
    source = str(arguments.get("source")).strip() if "source" in arguments else None
    evidence = str(arguments.get("evidence")).strip() if "evidence" in arguments else None
    return repo_memory_update(root, note_id, note=note, topic=topic, query=query, source=source, evidence=evidence)


def _handle_repo_memory_search(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    path = str(arguments.get("path") or "").strip() or None
    limit = int(arguments.get("limit") or 10)
    if not query:
        raise ValueError("repo_memory_search requires query")
    return repo_memory_search(root, query, path=path, limit=limit)


def _handle_repo_memory_topics(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    topic = str(arguments.get("topic") or "").strip() or None
    limit = int(arguments.get("limit") or 20)
    notes_per_topic = int(arguments.get("notes_per_topic") or 5)
    return repo_memory_topics(root, topic=topic, limit=limit, notes_per_topic=notes_per_topic)


def _handle_repo_file_notes(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    limit = int(arguments.get("limit") or 20)
    if not path:
        raise ValueError("repo_file_notes requires path")
    return repo_file_notes(root, path, limit=limit)


def _handle_repo_session_summary(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 10)
    return repo_session_summary(root, limit=limit)


def _debug_request_payload(request: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": request.get("id"),
        "method": request.get("method"),
        "keys": sorted(request.keys()),
    }
    if isinstance(request.get("params"), dict) and request.get("method") == "initialize":
        payload["protocolVersion"] = request["params"].get("protocolVersion")
    if isinstance(request.get("error"), dict):
        error = request["error"]
        payload["error"] = {
            "code": error.get("code"),
            "message": error.get("message"),
            "data": error.get("data"),
        }
    return payload


def _initialize_result(params: dict[str, Any] | None = None) -> dict[str, Any]:
    requested = (params or {}).get("protocolVersion")
    protocol_version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
    return {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "init-agent", "version": __version__},
    }


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "repo_graph_search",
            "description": "Search the local init-agent graph for a coding task and return candidate files, symbols and follow-up commands.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text task or question."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_overview",
            "description": "Return a broad local repository overview with likely entry points, manifests and subsystems.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "repo_entrypoints",
            "description": "Return a focused list of likely project entry points and supporting files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 12},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_related_file",
            "description": "Inspect one indexed file neighborhood: symbols, relations, calls, callers and recent commits.",
            "inputSchema": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Project-relative file path."}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_symbol_callers",
            "description": "Return definitions and caller files for a function, method, class or symbol name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Symbol name."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_feedback_add",
            "description": "Record local orientation feedback after an agent has verified whether a file was useful, noisy or missing for a query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Original or similar user task/query."},
                    "path": {"type": "string", "description": "Project-relative path being evaluated."},
                    "rating": {
                        "type": "string",
                        "enum": ["crucial", "useful", "neutral", "noisy", "missing"],
                        "description": "Use missing for important files absent from the original pack; use noisy for false positives.",
                    },
                    "reason": {"type": "string", "description": "Short factual reason; do not include source code snippets."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                },
                "required": ["query", "path", "rating"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_feedback_explain",
            "description": "Explain local feedback signals that would affect a similar query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query to explain."},
                    "include_all": {"type": "boolean", "default": False, "description": "Include ignored feedback entries."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_add",
            "description": "Record a short local note about what an agent learned after verifying a repository file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path."},
                    "scope": {"type": "string", "enum": ["file", "repo"], "default": "file", "description": "Use repo for project-wide notes that are not tied to one file."},
                    "note": {"type": "string", "description": "Short factual note; do not include source code snippets."},
                    "topic": {"type": "string", "description": "Optional topic such as badge messages or runtime entrypoints."},
                    "query": {"type": "string", "description": "Optional user task/query that led to the note."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "default": "agent"},
                    "evidence": {
                        "type": "string",
                        "enum": [
                            "read_full_file",
                            "read_excerpt",
                            "manifest_only",
                            "inferred_from_graph",
                            "user_decision",
                            "implementation_note",
                            "planning_note",
                        ],
                        "default": "read_excerpt",
                        "description": "How the note was verified.",
                    },
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_list",
            "description": "List local agent file notes, optionally filtered by path, topic or stale status.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional project-relative file path filter."},
                    "topic": {"type": "string", "description": "Optional exact topic filter."},
                    "scope": {"type": "string", "enum": ["file", "repo"], "description": "Optional memory scope filter."},
                    "stale_only": {"type": "boolean", "default": False, "description": "Return only stale or unknown-staleness notes."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_audit",
            "description": "Return quality signals for local memory notes, including stale, missing-topic, unknown-evidence and duplicate groups.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_session_summary",
            "description": "Return a compact local handoff summary with git status, recent memory, recent feedback and memory audit counts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_search",
            "description": "Search local agent file notes for a task, topic or question.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Task, topic or question to search in local notes."},
                    "path": {"type": "string", "description": "Optional project-relative file path filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_topics",
            "description": "Return topic-level aggregates from local agent memory notes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Optional exact topic filter."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "notes_per_topic": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_delete",
            "description": "Delete one local agent file note by id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Memory note id to delete."},
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_memory_update",
            "description": "Update one local agent file note by id and refresh its file hash when applicable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "minimum": 1, "description": "Memory note id to update."},
                    "note": {"type": "string", "description": "Replacement short factual note; do not include source code snippets."},
                    "topic": {"type": "string", "description": "Replacement topic."},
                    "query": {"type": "string", "description": "Replacement task/query that led to the note."},
                    "source": {"type": "string", "enum": ["agent", "user", "benchmark"], "description": "Replacement memory source."},
                    "evidence": {
                        "type": "string",
                        "enum": [
                            "read_full_file",
                            "read_excerpt",
                            "manifest_only",
                            "inferred_from_graph",
                            "user_decision",
                            "implementation_note",
                            "planning_note",
                        ],
                        "description": "Replacement evidence level.",
                    },
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "repo_file_notes",
            "description": "Return local agent notes attached to one project file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project-relative file path."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ]


def _tool_result(result: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(result, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": result,
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _read_message(stream: BufferedIOBase) -> JsonRpcMessage | None:
    first_line = _read_non_empty_line(stream)
    if first_line is None:
        return None
    if first_line.startswith(b"{"):
        return json.loads(first_line.decode("utf-8")), "jsonl"

    headers = [first_line]
    while True:
        header_line = stream.readline()
        if header_line == b"":
            raise ValueError("unexpected EOF while reading MCP headers")
        if header_line in {b"\r\n", b"\n"}:
            break
        headers.append(header_line.strip())

    content_length = None
    for header in headers:
        if header.lower().startswith(b"content-length:"):
            content_length = _parse_content_length(header)
            break
    if content_length is not None:
        body = stream.read(content_length)
        if len(body) != content_length:
            raise ValueError("unexpected EOF while reading MCP body")
        return json.loads(body.decode("utf-8")), "content_length"
    raise ValueError("missing MCP Content-Length header")


def _read_non_empty_line(stream: BufferedIOBase) -> bytes | None:
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line.strip():
            return line.strip()


def _parse_content_length(line: bytes) -> int:
    try:
        _, raw_value = line.decode("ascii").split(":", 1)
        length = int(raw_value.strip())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid MCP Content-Length header") from exc
    if length < 0:
        raise ValueError("invalid negative MCP Content-Length")
    return length


def _write_message(message: dict[str, Any], stream: BufferedIOBase | None = None, response_format: str = "content_length") -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    output = stream or sys.stdout.buffer
    if response_format == "jsonl":
        output.write(body + b"\n")
    else:
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        output.write(header + body)
    output.flush()


if __name__ == "__main__":
    raise SystemExit(main())
