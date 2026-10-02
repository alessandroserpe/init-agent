"""Minimal MCP stdio server for init-agent repo tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
from io import BufferedIOBase
from pathlib import Path
from typing import Any

from .repo_budget import WorkBudgetExceeded, budget_scope
from . import __version__
from .private_files import private_open
from .utils import terminal_safe
from .mcp_tools import MCP_TOOL_HANDLERS, MCP_TOOL_PROFILES, mcp_tool_definitions, mcp_tool_names


SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]


MAX_FRAME_BYTES = 256 * 1024
MAX_HEADER_LINE = 4096
MAX_HEADER_BYTES = 16 * 1024
MAX_HEADERS = 32
MAX_EMPTY_LINES = 16
MAX_JSON_DEPTH = 32
MAX_JSON_TOKENS = 8192
MAX_METHOD_LENGTH = 128


class FramingError(ValueError):
    """Fatal transport error; the unread remainder must never be dispatched."""


JsonRpcMessage = tuple[dict[str, Any], str]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="init-agent-mcp", description="Run the init-agent MCP stdio server.")
    parser.add_argument("--root", default=".", help="Repository root to serve. Defaults to the current directory.")
    parser.add_argument(
        "--profile",
        choices=MCP_TOOL_PROFILES,
        default="core",
        help="MCP tool surface: core for the daily agent loop, full for legacy/advanced tools.",
    )
    args = parser.parse_args(argv)
    server = InitAgentMcpServer(Path(args.root).resolve(), profile=args.profile)
    return server.serve()


class InitAgentMcpServer:
    """Small JSON-RPC server for MCP clients over stdin/stdout."""

    def __init__(self, root: Path, profile: str = "core") -> None:
        self.root = root
        self.profile = profile
        self.enabled_tools = mcp_tool_names(profile)
        self.debug_log = Path(os.environ["INIT_AGENT_MCP_DEBUG_LOG"]).expanduser() if os.environ.get("INIT_AGENT_MCP_DEBUG_LOG") else None

    def serve(self) -> int:
        self._debug("server_start", {"root": str(self.root), "version": __version__, "profile": self.profile})
        input_stream = sys.stdin.buffer
        output_stream = sys.stdout.buffer
        while True:
            response_format = "jsonl"
            try:
                read_result = _read_message(input_stream)
                if read_result is None:
                    self._debug("server_eof", {})
                    break
                request, response_format = read_result
                self._debug("request", _debug_request_payload(request))
                response = self.handle(request)
            except FramingError as exc:
                self._debug("framing_error", {"message": str(exc)})
                # Do not drain an attacker-controlled body or try to resynchronize.
                return 1
            except Exception as exc:
                self._debug("error", {"message": str(exc)})
                response = _error_response(None, -32603, str(exc))
            if response is not None:
                _write_message(response, output_stream, response_format=response_format)
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        _validate_envelope(request)
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
            return _result_response(request_id, {"tools": mcp_tool_definitions(self.profile)})
        if method == "tools/call":
            return _result_response(request_id, self._call_tool(params))
        if method == "ping":
            return _result_response(request_id, {})
        return _error_response(request_id, -32601, f"method not found: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name") or ""
        if not isinstance(name, str) or len(name) > MAX_METHOD_LENGTH:
            return _tool_error("invalid or oversized MCP tool name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        handler = MCP_TOOL_HANDLERS.get(name)
        if handler is None:
            return _tool_error(f"unknown tool: {name}")
        if name not in self.enabled_tools:
            return _tool_error(
                f"tool not enabled in MCP profile {self.profile}: {name}; "
                "start init-agent-mcp with --profile full for legacy and administrative tools"
            )
        try:
            with budget_scope():
                result = handler(self.root, arguments)
        except WorkBudgetExceeded as exc:
            result = _tool_error(str(exc))
            result["structuredContent"] = {"status": "error", "truncated": True, "error": str(exc)}
            return result
        except ValueError as exc:
            return _tool_error(str(exc))
        except Exception as exc:
            return _tool_error(f"{name} failed: {exc}")
        return _tool_result(result)

    def _debug(self, event: str, payload: dict[str, Any]) -> None:
        if self.debug_log is None:
            return
        try:
            self.debug_log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with private_open(self.debug_log, "a") as fh:
                fh.write(json.dumps({"event": event, **payload}, sort_keys=True) + "\n")
        except OSError as exc:
            print(terminal_safe(f"Could not write private debug log: {exc}"), file=sys.stderr)


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
    text = json.dumps(result, sort_keys=True, separators=(",", ":"))
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


def _validate_envelope(value: Any) -> None:
    if not isinstance(value, dict):
        raise FramingError("MCP request must be a JSON object")
    method = value.get("method")
    if method is not None and (not isinstance(method, str) or len(method) > MAX_METHOD_LENGTH):
        raise FramingError("invalid or oversized MCP method")
    request_id = value.get("id")
    if request_id is not None and (isinstance(request_id, bool) or not isinstance(request_id, (str, int)) or
                                   (isinstance(request_id, str) and len(request_id) > 256)):
        raise FramingError("invalid or oversized MCP request id")
    params = value.get("params")
    if method == "tools/call" and isinstance(params, dict):
        name = params.get("name")
        if name is not None and (not isinstance(name, str) or len(name) > MAX_METHOD_LENGTH):
            raise FramingError("invalid or oversized MCP tool name")


def _decode_frame(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_FRAME_BYTES:
        raise FramingError("MCP frame exceeds byte limit")
    # Check structure before json.loads can allocate recursive containers.
    depth = tokens = 0
    quoted = escaped = False
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
            tokens += 1
        elif char in (123, 91):
            depth += 1
            tokens += 1
        elif char in (125, 93):
            depth -= 1
        elif char in (44, 58):
            tokens += 1
        if depth > MAX_JSON_DEPTH or tokens > MAX_JSON_TOKENS:
            raise FramingError("MCP JSON exceeds structural limits")
    try:
        value = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise FramingError("invalid MCP JSON") from exc
    _validate_envelope(value)
    return value


def _read_message(stream: BufferedIOBase) -> JsonRpcMessage | None:
    first_line = _read_non_empty_line(stream)
    if first_line is None:
        return None
    if first_line.lstrip().startswith(b"{"):
        return _decode_frame(first_line), "jsonl"

    content_length = None
    header_bytes = count = 0
    header_line = first_line
    while header_line not in {b"\r\n", b"\n"}:
        if not header_line:
            raise FramingError("unexpected EOF while reading MCP headers")
        count += 1
        header_bytes += len(header_line)
        if count > MAX_HEADERS or len(header_line) > MAX_HEADER_LINE or header_bytes > MAX_HEADER_BYTES:
            raise FramingError("MCP headers exceed limits")
        if b":" not in header_line:
            raise FramingError("invalid MCP header")
        if header_line.lower().startswith(b"content-length:"):
            if content_length is not None:
                raise FramingError("duplicate MCP Content-Length")
            content_length = _parse_content_length(header_line)
        header_line = stream.readline(MAX_HEADER_LINE + 1)
    if content_length is None:
        raise FramingError("missing MCP Content-Length header")
    body = bytearray()
    while len(body) < content_length:
        chunk = stream.read(min(8192, content_length - len(body)))
        if not chunk:
            raise FramingError("unexpected EOF while reading MCP body")
        body.extend(chunk)
    return _decode_frame(bytes(body)), "content_length"


def _read_non_empty_line(stream: BufferedIOBase) -> bytes | None:
    for _ in range(MAX_EMPTY_LINES + 1):
        line = stream.readline(MAX_FRAME_BYTES + 1)
        if len(line) > MAX_FRAME_BYTES:
            raise FramingError("MCP frame exceeds byte limit")
        if not line:
            return None
        if line.strip():
            return line
    raise FramingError("too many empty MCP framing lines")


def _parse_content_length(line: bytes) -> int:
    raw_value = line.partition(b":")[2].strip()
    if not raw_value or len(raw_value) > 9 or not raw_value.isdigit():
        raise FramingError("invalid MCP Content-Length header")
    length = int(raw_value)
    if length > MAX_FRAME_BYTES:
        raise FramingError("MCP Content-Length exceeds byte limit")
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
