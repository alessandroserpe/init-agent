"""Minimal MCP stdio server for init-agent repo tools."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from io import BufferedIOBase
from pathlib import Path
from typing import Any

from . import __version__
from .agent_tools import repo_graph_search, repo_overview, repo_related_file, repo_symbol_callers


PROTOCOL_VERSION = "2024-11-05"


ToolHandler = Callable[[Path, dict[str, Any]], dict[str, Any]]


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

    def serve(self) -> int:
        input_stream = sys.stdin.buffer
        output_stream = sys.stdout.buffer
        while True:
            try:
                request = _read_message(input_stream)
                if request is None:
                    break
                response = self.handle(request)
            except Exception as exc:
                response = _error_response(None, -32603, str(exc))
            if response is not None:
                _write_message(response, output_stream)
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") if isinstance(request.get("params"), dict) else {}

        if method == "initialize":
            return _result_response(request_id, _initialize_result())
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
            "repo_overview": _handle_repo_overview,
            "repo_related_file": _handle_repo_related_file,
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


def _handle_repo_graph_search(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("repo_graph_search requires query")
    limit = int(arguments.get("limit") or 10)
    return repo_graph_search(root, query, limit=limit, prepare=False)


def _handle_repo_overview(root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    return repo_overview(root, prepare=False)


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


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
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


def _read_message(stream: BufferedIOBase) -> dict[str, Any] | None:
    first_line = _read_non_empty_line(stream)
    if first_line is None:
        return None
    if first_line.startswith(b"{"):
        return json.loads(first_line.decode("utf-8"))

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
        return json.loads(body.decode("utf-8"))
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


def _write_message(message: dict[str, Any], stream: BufferedIOBase | None = None) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    output = stream or sys.stdout.buffer
    output.write(header + body)
    output.flush()


if __name__ == "__main__":
    raise SystemExit(main())
