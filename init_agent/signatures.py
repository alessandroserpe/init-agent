"""Bounded declaration summaries; source bodies are never signature metadata."""

from __future__ import annotations

import re

MAX_SIGNATURE_BYTES = 256
MAX_DECLARATION_CHARS = 4096
_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
# Redact literals before examining parameter syntax, including unterminated ones.
_LITERALS = re.compile(r'''"(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|`(?:\\.|[^`\\])*(?:`|$)''')


def _bounded(value: str) -> str:
    return value.encode("utf-8", errors="replace")[:MAX_SIGNATURE_BYTES].decode("utf-8", errors="ignore")


def minimize_signature(name: str, kind: str, signature: str | None) -> str:
    """Rebuild code signatures from names/parameter shapes, never raw lines.

    This also handles signatures from old databases. Documentation commands and
    entry points are intentionally retained as bounded metadata, not code bodies.
    """
    name = _bounded(str(name))
    kind = str(kind)
    raw = str(signature or "")[:MAX_DECLARATION_CHARS]
    if kind in {"heading", "command_example", "config_key", "package_script", "project_script", "project_entry_point"}:
        return _bounded(raw)
    if kind == "route":
        return _bounded(f"route {name}")
    if kind == "constant":
        return _bounded(f"{name} = ...")
    if kind not in {"function", "method"}:
        return _bounded(f"{kind} {name}")

    declaration = re.search(r"\b(async\s+def|def|function|func|fn)\s+", raw)
    prefix = declaration.group(1) if declaration else "function"
    # Locate this declaration's name, rather than an earlier call on the line.
    match = re.search(r"(?<![\w$])" + re.escape(name) + r"\s*\(", raw)
    params = "..."
    if match:
        params = _parameter_shapes(raw[match.end():])
    suffix = ":" if prefix in {"def", "async def"} else ""
    return _bounded(f"{prefix} {name}({params}){suffix}")


def _parameter_shapes(raw: str) -> str:
    raw = _LITERALS.sub("...", raw)
    # Comments can contain literals or arbitrary source, so omit the entire list.
    if any(marker in raw.split(")", 1)[0] for marker in ("//", "/*", "#")):
        return "..."
    parts = []
    stack: list[str] = []
    start = 0
    pairs = {"(": ")", "[": "]", "{": "}"}
    for index, char in enumerate(raw):
        if char == ")" and not stack:
            parts.append(raw[start:index])
            break
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")]}":
            if not stack or stack.pop() != char:
                return "..."
        elif char == "," and not stack:
            parts.append(raw[start:index])
            start = index + 1
        if len(parts) >= 32 or len(stack) > 32:
            return "..."
    else:
        return "..."
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in {"/", "*", "..."}:
            result.append(part)
            continue
        head, equals, _default = part.partition("=")
        head = head.strip()
        # Allow names and simple type shapes; expressions and destructuring fail closed.
        if not re.fullmatch(r"[A-Za-z_$*&][A-Za-z0-9_$*&\s:.?\[\]|<>,-]*", head):
            result.append("...")
            continue
        head = re.sub(r"\s+", " ", head)
        result.append(head + ("=..." if equals else ""))
    return ", ".join(result)
