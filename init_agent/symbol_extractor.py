"""Regex-based symbol and dependency extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedSymbol:
    name: str
    kind: str
    line: int
    signature: str


@dataclass(frozen=True)
class ExtractedRelation:
    relation: str
    target_type: str
    target: str
    line: int
    confidence: float = 0.75


PY_DEF_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")
PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b([^:]*)")
PY_CONSTANT_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=")
PY_IMPORT_RE = re.compile(r"^\s*import\s+(.+)$")
PY_FROM_RE = re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+(.+)$")

PHP_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b")
PHP_CONST_RE = re.compile(r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")
PHP_DEFINE_RE = re.compile(r"\bdefine\s*\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")
PHP_INCLUDE_RE = re.compile(
    r"\b(include|include_once|require|require_once)\s*(?:\(?\s*)[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)

JS_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
JS_CONST_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")
JS_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")
JS_IMPORT_RE = re.compile(r"\bimport\s+.*?\s+from\s+[\"']([^\"']+)[\"']")
JS_SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s+[\"']([^\"']+)[\"']")
JS_REQUIRE_RE = re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)")


def extract_symbols_and_relations(content: str | None, language: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    if content is None:
        return [], []
    if language == "python":
        return _extract_python(content)
    if language == "php":
        return _extract_php(content)
    if language in {"javascript", "typescript"}:
        return _extract_js_ts(content)
    return [], []


def _extract_python(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    class_indent: int | None = None
    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if class_indent is not None and stripped and indent <= class_indent and not stripped.startswith("@"):
            class_indent = None
        if match := PY_DEF_RE.match(line):
            kind = "method" if class_indent is not None and indent > class_indent else "function"
            symbols.append(ExtractedSymbol(match.group(1), kind, line_no, stripped))
        if match := PY_CLASS_RE.match(line):
            class_indent = indent
            symbols.append(ExtractedSymbol(match.group(1), "class", line_no, stripped))
        if match := PY_CONSTANT_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, stripped))
        if match := PY_IMPORT_RE.match(line):
            for module in _split_imports(match.group(1)):
                relations.append(ExtractedRelation("imports", "module", module, line_no, 0.65))
        if match := PY_FROM_RE.match(line):
            relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.75))
    return symbols, relations


def _extract_php(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    in_class = False
    class_brace_balance = 0
    for line_no, line in enumerate(content.splitlines(), start=1):
        class_match = PHP_CLASS_RE.search(line)
        if class_match:
            in_class = True
            class_brace_balance = max(class_brace_balance, 0)
            symbols.append(ExtractedSymbol(class_match.group(1), "class", line_no, line.strip()))
        if match := PHP_FUNCTION_RE.search(line):
            kind = "method" if in_class else "function"
            symbols.append(ExtractedSymbol(match.group(1), kind, line_no, line.strip()))
        if match := PHP_CONST_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, line.strip()))
        if match := PHP_DEFINE_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, line.strip()))
        if match := PHP_INCLUDE_RE.search(line):
            relations.append(ExtractedRelation(match.group(1).lower(), "file", match.group(2), line_no, 0.8))
        if in_class:
            class_brace_balance += line.count("{") - line.count("}")
            if class_brace_balance <= 0 and "}" in line:
                in_class = False
    return symbols, relations


def _extract_js_ts(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        if match := JS_FUNCTION_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "function", line_no, line.strip()))
        if match := JS_CONST_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, line.strip()))
        if match := JS_CLASS_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "class", line_no, line.strip()))
        for pattern in (JS_IMPORT_RE, JS_SIDE_EFFECT_IMPORT_RE, JS_REQUIRE_RE):
            if match := pattern.search(line):
                relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.75))
    return symbols, relations


def _split_imports(value: str) -> list[str]:
    names = []
    for part in value.split(","):
        name = part.strip().split(" as ")[0].strip()
        if name:
            names.append(name)
    return names
