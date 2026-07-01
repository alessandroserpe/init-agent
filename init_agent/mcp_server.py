"""Minimal MCP stdio server for init-agent repo tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
from io import BufferedIOBase
from pathlib import Path
from typing import Any

from . import __version__
from .mcp_tools import MCP_TOOL_HANDLERS, mcp_tool_definitions


SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]


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
            return _result_response(request_id, {"tools": mcp_tool_definitions()})
        if method == "tools/call":
            return _result_response(request_id, self._call_tool(params))
        if method == "ping":
            return _result_response(request_id, {})
        return _error_response(request_id, -32601, f"method not found: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        handler = MCP_TOOL_HANDLERS.get(name)
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
