"""Regex-based symbol and dependency extraction."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


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


PY_DEF_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
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
PHP_CALL_RE = re.compile(r"(?<!->)(?<!::)\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_CALL_EXCLUDES = {
    "__",
    "array",
    "array_filter",
    "array_key_exists",
    "array_keys",
    "array_map",
    "array_merge",
    "array_pop",
    "array_push",
    "array_shift",
    "array_unique",
    "array_values",
    "basename",
    "catch",
    "count",
    "date",
    "declare",
    "die",
    "echo",
    "empty",
    "eval",
    "exit",
    "explode",
    "file_exists",
    "file_get_contents",
    "file_put_contents",
    "filter_input",
    "for",
    "foreach",
    "function",
    "header",
    "htmlentities",
    "htmlspecialchars",
    "http_response_code",
    "implode",
    "in_array",
    "is_array",
    "is_bool",
    "is_int",
    "is_numeric",
    "is_string",
    "if",
    "include",
    "include_once",
    "isset",
    "json_decode",
    "json_encode",
    "list",
    "md5",
    "mysqli_error",
    "mysqli_fetch_array",
    "mysqli_fetch_assoc",
    "mysqli_fetch_object",
    "mysqli_insert_id",
    "mysqli_num_rows",
    "mysqli_query",
    "mysqli_real_escape_string",
    "number_format",
    "preg_match",
    "preg_replace",
    "print",
    "print_r",
    "require",
    "require_once",
    "return",
    "session_start",
    "sizeof",
    "sprintf",
    "str_replace",
    "strlen",
    "strpos",
    "strtolower",
    "strtotime",
    "strtoupper",
    "substr",
    "switch",
    "time",
    "trim",
    "unset",
    "urlencode",
    "var_dump",
    "while",
}

JS_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
JS_CONST_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")
JS_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")
JS_IMPORT_RE = re.compile(r"\bimport\s+.*?\s+from\s+[\"']([^\"']+)[\"']")
JS_SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s+[\"']([^\"']+)[\"']")
JS_REQUIRE_RE = re.compile(r"\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)")

GO_FUNCTION_RE = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
GO_TYPE_RE = re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(struct|interface)\b")
GO_CONST_VAR_RE = re.compile(r"^\s*(?:const|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
GO_IMPORT_SINGLE_RE = re.compile(r"^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"")
GO_IMPORT_GROUP_RE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"")

RUST_FUNCTION_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*[<(]")
RUST_TYPE_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
RUST_IMPL_RE = re.compile(r"^\s*impl(?:<[^>]+>)?\s+(?:[A-Za-z_][A-Za-z0-9_:<>]*\s+for\s+)?([A-Za-z_][A-Za-z0-9_:<>]*)")
RUST_CONST_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*:")
RUST_USE_RE = re.compile(r"^\s*(?:pub\s+)?use\s+([^;]+);")
RUST_MOD_RE = re.compile(r"^\s*(?:pub\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;?")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*```\s*([A-Za-z0-9_-]*)\s*$")
COMMAND_LANGUAGES = {"", "bash", "sh", "shell", "console", "zsh", "powershell", "pwsh"}
COMMAND_PROMPT_RE = re.compile(r"^\s*(?:[$#>]\s*)?(.+?)\s*$")
YAML_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(?:.*)$")


def extract_symbols_and_relations(
    content: str | None,
    language: str,
    path: str | None = None,
) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    if content is None:
        return [], []
    file_name = Path(path or "").name.lower()
    if language == "markdown":
        return _extract_markdown(content, file_name)
    if language == "json":
        return _extract_json_config(content, file_name)
    if language == "toml":
        return _extract_toml_config(content, file_name)
    if language == "yaml":
        return _extract_yaml_config(content)
    if language == "python":
        return _extract_python(content)
    if language == "php":
        return _extract_php(content)
    if language in {"javascript", "typescript"}:
        return _extract_js_ts(content)
    if language == "go":
        return _extract_go(content)
    if language == "rust":
        return _extract_rust(content)
    return [], []


def _extract_markdown(content: str, file_name: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    in_fence = False
    fence_language = ""
    collect_commands = file_name.startswith("readme")
    for line_no, line in enumerate(content.splitlines(), start=1):
        if match := FENCE_RE.match(line):
            in_fence = not in_fence
            fence_language = match.group(1).lower() if in_fence else ""
            continue
        if in_fence:
            if collect_commands and fence_language in COMMAND_LANGUAGES:
                command = _command_from_line(line)
                if command:
                    symbols.append(ExtractedSymbol(command[:120], "command_example", line_no, command[:200]))
            continue
        if match := MARKDOWN_HEADING_RE.match(line):
            heading = _clean_heading(match.group(2))
            if heading:
                symbols.append(ExtractedSymbol(heading[:120], "heading", line_no, line.strip()[:200]))
    return symbols, []


def _extract_json_config(content: str, file_name: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return symbols, []
    if isinstance(data, dict):
        for key in sorted(data):
            symbols.append(ExtractedSymbol(str(key), "config_key", 1, str(key)))
        if file_name == "package.json":
            scripts = data.get("scripts")
            if isinstance(scripts, dict):
                for name, command in sorted(scripts.items()):
                    symbols.append(ExtractedSymbol(str(name), "package_script", 1, str(command)[:200]))
    return symbols, []


def _extract_toml_config(content: str, file_name: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return symbols, []
    for key in sorted(data):
        symbols.append(ExtractedSymbol(str(key), "config_key", 1, str(key)))
    if file_name == "pyproject.toml":
        symbols.extend(_pyproject_scripts(data))
    return symbols, []


def _extract_yaml_config(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    seen: set[str] = set()
    for line_no, line in enumerate(content.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            continue
        if match := YAML_TOP_LEVEL_KEY_RE.match(line):
            key = match.group(1)
            if key not in seen:
                seen.add(key)
                symbols.append(ExtractedSymbol(key, "config_key", line_no, key))
    return symbols, []


def _pyproject_scripts(data: dict[str, object]) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    project = data.get("project")
    if isinstance(project, dict):
        for table_name in ("scripts", "gui-scripts"):
            table = project.get(table_name)
            if isinstance(table, dict):
                for name, target in sorted(table.items()):
                    symbols.append(ExtractedSymbol(str(name), "project_script", 1, str(target)[:200]))
        entry_points = project.get("entry-points")
        if isinstance(entry_points, dict):
            for group_name, table in sorted(entry_points.items()):
                if isinstance(table, dict):
                    for name, target in sorted(table.items()):
                        symbols.append(ExtractedSymbol(f"{group_name}:{name}", "project_entry_point", 1, str(target)[:200]))
    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            scripts = poetry.get("scripts")
            if isinstance(scripts, dict):
                for name, target in sorted(scripts.items()):
                    symbols.append(ExtractedSymbol(str(name), "project_script", 1, str(target)[:200]))
    return symbols


def _command_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = COMMAND_PROMPT_RE.match(stripped)
    if not match:
        return None
    command = match.group(1).strip()
    if not command or command in {"```", "..."}:
        return None
    return command


def _clean_heading(text: str) -> str:
    text = text.strip().strip("#").strip()
    text = re.sub(r"\s+", " ", text)
    return text


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
        for call_name in _php_calls_in_line(line):
            relations.append(ExtractedRelation("calls", "symbol_name", call_name, line_no, 0.45))
        if in_class:
            class_brace_balance += line.count("{") - line.count("}")
            if class_brace_balance <= 0 and "}" in line:
                in_class = False
    return symbols, relations


def _php_calls_in_line(line: str) -> list[str]:
    line = PHP_FUNCTION_RE.sub("", line, count=1)
    cleaned = _strip_php_line_noise(line)
    calls: list[str] = []
    for match in PHP_CALL_RE.finditer(cleaned):
        name = match.group(1)
        if name.lower() in PHP_CALL_EXCLUDES:
            continue
        if name not in calls:
            calls.append(name)
    return calls


def _strip_php_line_noise(line: str) -> str:
    without_comment = re.split(r"//|#", line, maxsplit=1)[0]
    without_comment = re.sub(r"/\*.*?\*/", "", without_comment)
    return re.sub(r"""(["']).*?\1""", '""', without_comment)


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


def _extract_go(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    in_import_group = False
    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if match := GO_FUNCTION_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "function", line_no, stripped))
        if match := GO_TYPE_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), match.group(2), line_no, stripped))
        if match := GO_CONST_VAR_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, stripped))
        if stripped.startswith("import ("):
            in_import_group = True
            continue
        if in_import_group and stripped == ")":
            in_import_group = False
            continue
        if match := GO_IMPORT_SINGLE_RE.match(line):
            relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.75))
        elif in_import_group and (match := GO_IMPORT_GROUP_RE.match(line)):
            relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.75))
    return symbols, relations


def _extract_rust(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if match := RUST_FUNCTION_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "function", line_no, stripped))
        if match := RUST_TYPE_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(2), match.group(1), line_no, stripped))
        if match := RUST_IMPL_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1).split("::")[-1], "impl", line_no, stripped))
        if match := RUST_CONST_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, stripped))
        if match := RUST_USE_RE.match(line):
            relations.append(ExtractedRelation("imports", "module", _rust_use_root(match.group(1)), line_no, 0.7))
        if match := RUST_MOD_RE.match(line):
            relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.7))
    return symbols, relations


def _rust_use_root(value: str) -> str:
    cleaned = value.strip().lstrip("::")
    return re.split(r"::|[{,]", cleaned, maxsplit=1)[0].strip()


def _split_imports(value: str) -> list[str]:
    names = []
    for part in value.split(","):
        name = part.strip().split(" as ")[0].strip()
        if name:
            names.append(name)
    return names
