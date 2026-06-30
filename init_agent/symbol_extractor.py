"""Regex-based symbol and dependency extraction."""

from __future__ import annotations

import json
import re
import tomllib
import ast
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
PHP_ROUTE_ARRAY_RE = re.compile(r"""['"](?P<path>/[^'"]*)['"]\s*=>\s*['"](?P<handler>[A-Za-z_][A-Za-z0-9_:@\\.-]*)['"]""")
PHP_ROUTE_CALL_RE = re.compile(
    r"""\b(?:Route::|\$?(?:router|app)->)?(?P<method>get|post|put|patch|delete|any|match)\s*\(\s*['"](?P<path>/[^'"]*)['"]\s*,\s*(?P<handler>[^),]+)""",
    re.IGNORECASE,
)
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
JS_ROUTE_RE = re.compile(
    r"""\b(?:app|router|server|fastify)\.(?P<method>get|post|put|patch|delete|all|route)\s*\(\s*['"](?P<path>/[^'"]*)['"]\s*,\s*(?P<handler>[A-Za-z_$][A-Za-z0-9_$]*)?""",
    re.IGNORECASE,
)
JS_FASTIFY_ROUTE_RE = re.compile(r"""\b(?:fastify|server)\.route\s*\(\s*\{""")
JS_OBJECT_METHOD_RE = re.compile(r"""\bmethod\s*:\s*['"](?P<method>[A-Z]+)['"]""")
JS_OBJECT_URL_RE = re.compile(r"""\b(?:url|path)\s*:\s*['"](?P<path>/[^'"]*)['"]""")
JS_OBJECT_HANDLER_RE = re.compile(r"""\bhandler\s*:\s*(?P<handler>[A-Za-z_$][A-Za-z0-9_$]*)""")
JS_CALL_RE = re.compile(r"(?<!function\s)\b([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
JS_CALL_EXCLUDES = {
    "describe",
    "expect",
    "fetch",
    "if",
    "it",
    "render",
    "return",
    "test",
}

GO_FUNCTION_RE = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")
GO_TYPE_RE = re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(struct|interface)\b")
GO_CONST_VAR_RE = re.compile(r"^\s*(?:const|var)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
GO_IMPORT_SINGLE_RE = re.compile(r"^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"")
GO_IMPORT_GROUP_RE = re.compile(r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?\"([^\"]+)\"")
GIN_ROUTE_RE = re.compile(
    r"""\b[A-Za-z_][A-Za-z0-9_]*\.(?P<method>GET|POST|PUT|PATCH|DELETE|Any|Handle)\s*\(\s*"(?P<path>/[^"]*)"\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_.]*)""",
)

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
FLASK_ROUTE_RE = re.compile(
    r"""^\s*@(?:[A-Za-z_][A-Za-z0-9_]*\.)?(?:route|get|post|put|patch|delete)\s*\(\s*['"](?P<path>/[^'"]*)['"]"""
)
DJANGO_PATH_RE = re.compile(r"""^\s*(?:path|re_path)\s*\(\s*['"](?P<path>[^'"]*)['"]\s*,\s*(?P<handler>[A-Za-z_][A-Za-z0-9_.]*)""")
PY_CALL_EXCLUDES = {
    "__import__",
    "abs",
    "all",
    "any",
    "bool",
    "bytes",
    "callable",
    "chr",
    "classmethod",
    "dict",
    "dir",
    "enumerate",
    "filter",
    "float",
    "format",
    "getattr",
    "hasattr",
    "hash",
    "help",
    "id",
    "input",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "open",
    "ord",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "vars",
    "zip",
}


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
        return _extract_python(content, path)
    if language == "php":
        return _extract_php(content)
    if language in {"javascript", "typescript"}:
        return _extract_js_ts(content)
    if language == "go":
        return _extract_go(content)
    if language == "rust":
        return _extract_rust(content)
    return [], []


SQL_TABLE_RE = re.compile(
    r"\b(?:from|join|into|update)\s+[`\"']?([A-Za-z_][A-Za-z0-9_\.]*)[`\"']?",
    re.IGNORECASE,
)


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


def _extract_python(content: str, path: str | None = None) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    try:
        return _extract_python_ast(content, path)
    except SyntaxError:
        return _extract_python_regex(content, path)


def _extract_python_ast(content: str, path: str | None = None) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    tree = ast.parse(content)
    lines = content.splitlines()
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_depth = 0

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            symbols.append(ExtractedSymbol(node.name, "class", node.lineno, _python_line(lines, node.lineno)))
            self.class_depth += 1
            self.generic_visit(node)
            self.class_depth -= 1

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            kind = "method" if self.class_depth else "function"
            symbols.append(ExtractedSymbol(node.name, kind, node.lineno, _python_line(lines, node.lineno)))
            for route, route_line, route_signature in _python_flask_routes_from_decorators(node.decorator_list, lines):
                symbols.append(ExtractedSymbol(route, "route", route_line, route_signature))
                relations.append(ExtractedRelation("route_to_handler", "symbol_name", node.name, route_line, 0.8))
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> None:
            self._record_constant_targets(node.targets, node.lineno)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._record_constant_targets([node.target], node.lineno)
            self.generic_visit(node)

        def _record_constant_targets(self, targets: list[ast.expr], line_no: int) -> None:
            for target in targets:
                if isinstance(target, ast.Name) and PY_CONSTANT_RE.match(f"{target.id} ="):
                    symbols.append(ExtractedSymbol(target.id, "constant", line_no, _python_line(lines, line_no)))

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                relations.append(ExtractedRelation("imports", "module", alias.name, node.lineno, 0.65))
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                module = _python_import_module(path, node.module, node.level)
                relations.append(ExtractedRelation("imports", "module", module, node.lineno, 0.75))
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if route := _python_django_route_from_call(node, lines):
                route_path, handler, line_no, signature = route
                symbols.append(ExtractedSymbol(route_path, "route", line_no, signature))
                if handler:
                    relations.append(ExtractedRelation("route_to_handler", "symbol_name", handler, line_no, 0.65))
            if call_name := _python_call_name(node.func):
                if call_name not in PY_CALL_EXCLUDES:
                    relations.append(ExtractedRelation("calls", "symbol_name", call_name, node.lineno, 0.45))
            if template := _python_render_template(node):
                relations.append(ExtractedRelation("renders_template", "template", template, node.lineno, 0.7))
            self.generic_visit(node)

    Visitor().visit(tree)
    return symbols, relations


def _extract_python_regex(content: str, path: str | None = None) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []
    class_indent: int | None = None
    pending_flask_routes: list[tuple[str, int, str]] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if class_indent is not None and stripped and indent <= class_indent and not stripped.startswith("@"):
            class_indent = None
        if match := FLASK_ROUTE_RE.match(line):
            route = _normalize_route_path(match.group("path"))
            pending_flask_routes.append((route, line_no, stripped))
        if match := PY_DEF_RE.match(line):
            kind = "method" if class_indent is not None and indent > class_indent else "function"
            symbols.append(ExtractedSymbol(match.group(1), kind, line_no, stripped))
            for route, route_line, route_signature in pending_flask_routes:
                symbols.append(ExtractedSymbol(route, "route", route_line, route_signature))
                relations.append(ExtractedRelation("route_to_handler", "symbol_name", match.group(1), route_line, 0.8))
            pending_flask_routes = []
        if match := PY_CLASS_RE.match(line):
            class_indent = indent
            symbols.append(ExtractedSymbol(match.group(1), "class", line_no, stripped))
        if match := PY_CONSTANT_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, stripped))
        if match := PY_IMPORT_RE.match(line):
            for module in _split_imports(match.group(1)):
                relations.append(ExtractedRelation("imports", "module", module, line_no, 0.65))
        if match := PY_FROM_RE.match(line):
            relations.append(ExtractedRelation("imports", "module", _python_import_module_from_string(path, match.group(1)), line_no, 0.75))
        if match := DJANGO_PATH_RE.match(line):
            route = _normalize_route_path("/" + match.group("path").strip("/"))
            symbols.append(ExtractedSymbol(route, "route", line_no, stripped))
            relations.append(ExtractedRelation("route_to_handler", "symbol_name", match.group("handler").split(".")[-1], line_no, 0.65))
    return symbols, relations


def _python_line(lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def _python_call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _python_call_name(node.value)
    return ""


def _python_flask_routes_from_decorators(decorators: list[ast.expr], lines: list[str]) -> list[tuple[str, int, str]]:
    routes: list[tuple[str, int, str]] = []
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        call_name = _python_dotted_name(decorator.func)
        if call_name.split(".")[-1] not in {"route", "get", "post", "put", "patch", "delete"}:
            continue
        route = _first_string_arg(decorator)
        if route and route.startswith("/"):
            routes.append((_normalize_route_path(route), decorator.lineno, _python_line(lines, decorator.lineno)))
    return routes


def _python_django_route_from_call(node: ast.Call, lines: list[str]) -> tuple[str, str, int, str] | None:
    call_name = _python_dotted_name(node.func)
    if call_name.split(".")[-1] not in {"path", "re_path"}:
        return None
    route = _first_string_arg(node)
    if route is None:
        return None
    handler = ""
    if len(node.args) >= 2:
        handler = _python_call_handler_name(node.args[1])
    return _normalize_route_path("/" + route.strip("/")), handler, node.lineno, _python_line(lines, node.lineno)


def _first_string_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _python_call_handler_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _python_import_module(path: str | None, module: str, level: int) -> str:
    if level <= 0:
        return module
    current = Path(path or "")
    parts = list(current.with_suffix("").parts[:-1])
    if level > 1:
        parts = parts[: -(level - 1)] if level - 1 <= len(parts) else []
    if module:
        parts.extend(module.split("."))
    return ".".join(part for part in parts if part)


def _python_import_module_from_string(path: str | None, module: str) -> str:
    if not module.startswith("."):
        return module
    level = len(module) - len(module.lstrip("."))
    return _python_import_module(path, module.lstrip("."), level)


def _python_render_template(node: ast.Call) -> str:
    call_name = _python_dotted_name(node.func)
    if call_name.split(".")[-1] not in {"render", "TemplateResponse"}:
        return ""
    for arg in node.args[1:3]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return ""


def _python_dotted_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _python_dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _extract_php(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    try:
        ts_symbols, ts_relations = _extract_php_tree_sitter(content)
    except Exception:
        return _extract_php_regex(content)
    regex_symbols, regex_relations = _extract_php_regex(content)
    symbols = _dedupe_symbols(
        [
            *ts_symbols,
            *(symbol for symbol in regex_symbols if symbol.kind in {"constant", "route"}),
        ]
    )
    relations = _dedupe_relations(
        [
            *ts_relations,
            *(relation for relation in regex_relations if relation.relation == "route_to_handler"),
        ]
    )
    return symbols, relations


def _extract_php_regex(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
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
        for route, handler in _php_routes_in_line(line):
            symbols.append(ExtractedSymbol(route, "route", line_no, line.strip()))
            if handler:
                relations.append(ExtractedRelation("route_to_handler", "symbol_name", handler, line_no, 0.65))
        for call_name in _php_calls_in_line(line):
            relations.append(ExtractedRelation("calls", "symbol_name", call_name, line_no, 0.45))
        for table in _sql_tables_in_text(line):
            relations.append(ExtractedRelation("uses_table", "sql_table", table, line_no, 0.6))
        if in_class:
            class_brace_balance += line.count("{") - line.count("}")
            if class_brace_balance <= 0 and "}" in line:
                in_class = False
    return symbols, relations


def _extract_php_tree_sitter(content: str) -> tuple[list[ExtractedSymbol], list[ExtractedRelation]]:
    parser, language = _php_tree_sitter_parser()
    parser.language = language
    source = content.encode("utf-8", "ignore")
    tree = parser.parse(source)
    symbols: list[ExtractedSymbol] = []
    relations: list[ExtractedRelation] = []

    def walk(node: object) -> None:
        node_type = getattr(node, "type", "")
        line_no = getattr(node, "start_point")[0] + 1
        if node_type == "class_declaration":
            if name := _tree_sitter_name(source, node):
                symbols.append(ExtractedSymbol(name, "class", line_no, _tree_sitter_line(content, line_no)))
        elif node_type in {"interface_declaration", "trait_declaration", "enum_declaration"}:
            if name := _tree_sitter_name(source, node):
                symbols.append(ExtractedSymbol(name, node_type.removesuffix("_declaration"), line_no, _tree_sitter_line(content, line_no)))
        elif node_type == "function_definition":
            if name := _tree_sitter_name(source, node):
                symbols.append(ExtractedSymbol(name, "function", line_no, _tree_sitter_line(content, line_no)))
        elif node_type == "method_declaration":
            if name := _tree_sitter_name(source, node):
                symbols.append(ExtractedSymbol(name, "method", line_no, _tree_sitter_line(content, line_no)))
        elif node_type in {"function_call_expression", "member_call_expression", "scoped_call_expression"}:
            if name := _tree_sitter_call_name(source, node):
                if name.lower() not in PHP_CALL_EXCLUDES and not _tree_sitter_php_route_call(source, node, name):
                    relations.append(ExtractedRelation("calls", "symbol_name", name, line_no, 0.45))
        elif node_type in {"include_expression", "include_once_expression", "require_expression", "require_once_expression"}:
            if target := _tree_sitter_first_string(source, node):
                relations.append(ExtractedRelation(node_type.removesuffix("_expression"), "file", target, line_no, 0.8))
        for child in getattr(node, "named_children", []):
            walk(child)

    walk(tree.root_node)
    for line_no, line in enumerate(content.splitlines(), start=1):
        for table in _sql_tables_in_text(line):
            relations.append(ExtractedRelation("uses_table", "sql_table", table, line_no, 0.6))
    return symbols, relations


def _php_tree_sitter_parser() -> tuple[object, object]:
    from tree_sitter import Language, Parser  # type: ignore[import-not-found]
    import tree_sitter_php  # type: ignore[import-not-found]

    language_fn = getattr(tree_sitter_php, "language_php", None) or getattr(tree_sitter_php, "language", None)
    if language_fn is None:
        raise ImportError("tree_sitter_php does not expose a PHP language")
    return Parser(), Language(language_fn())


def _tree_sitter_text(source: bytes, node: object) -> str:
    return source[getattr(node, "start_byte") : getattr(node, "end_byte")].decode("utf-8", "ignore")


def _tree_sitter_line(content: str, line_no: int) -> str:
    lines = content.splitlines()
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def _tree_sitter_name(source: bytes, node: object) -> str:
    name_node = getattr(node, "child_by_field_name")("name")
    if name_node is None:
        name_node = _tree_sitter_first_identifier(node)
    if name_node is None:
        return ""
    return _tree_sitter_text(source, name_node).lstrip("\\")


def _tree_sitter_call_name(source: bytes, node: object) -> str:
    name_node = getattr(node, "child_by_field_name")("function") or getattr(node, "child_by_field_name")("name")
    if name_node is None:
        name_node = _tree_sitter_first_identifier(node)
    if name_node is None:
        return ""
    name = _tree_sitter_text(source, name_node).lstrip("\\")
    if "->" in name:
        return name.rsplit("->", 1)[-1]
    if "::" in name:
        return name.rsplit("::", 1)[-1]
    if "\\" in name:
        return name.rsplit("\\", 1)[-1]
    return name


def _tree_sitter_php_route_call(source: bytes, node: object, name: str) -> bool:
    if name.lower() not in {"get", "post", "put", "patch", "delete", "any", "match"}:
        return False
    route = _tree_sitter_first_string(source, node)
    return route.startswith("/")


def _tree_sitter_first_identifier(node: object) -> object | None:
    queue = list(getattr(node, "named_children", []))
    while queue:
        current = queue.pop(0)
        if getattr(current, "type", "") in {"identifier", "name", "variable_name"}:
            return current
        queue[0:0] = list(getattr(current, "named_children", []))
    return None


def _tree_sitter_first_string(source: bytes, node: object) -> str:
    queue = list(getattr(node, "named_children", []))
    while queue:
        current = queue.pop(0)
        if getattr(current, "type", "") in {"string", "string_value", "encapsed_string"}:
            value = _tree_sitter_text(source, current).strip()
            return value.strip("\"'")
        queue[0:0] = list(getattr(current, "named_children", []))
    return ""


def _dedupe_symbols(symbols: list[ExtractedSymbol]) -> list[ExtractedSymbol]:
    seen: set[tuple[str, str, int]] = set()
    deduped: list[ExtractedSymbol] = []
    for symbol in symbols:
        key = (symbol.name, symbol.kind, symbol.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return deduped


def _dedupe_relations(relations: list[ExtractedRelation]) -> list[ExtractedRelation]:
    seen: set[tuple[str, str, str, int]] = set()
    deduped: list[ExtractedRelation] = []
    for relation in relations:
        key = (relation.relation, relation.target_type, relation.target, relation.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(relation)
    return deduped


def _php_routes_in_line(line: str) -> list[tuple[str, str | None]]:
    routes: list[tuple[str, str | None]] = []
    for match in PHP_ROUTE_ARRAY_RE.finditer(line):
        handler = match.group("handler")
        if _looks_like_php_route_handler(handler):
            routes.append((_normalize_route_path(match.group("path")), handler.split("@")[-1].split("::")[-1]))
    for match in PHP_ROUTE_CALL_RE.finditer(line):
        handler = _handler_name(match.group("handler"))
        routes.append((_normalize_route_path(match.group("path")), handler))
    return routes


def _looks_like_php_route_handler(handler: str) -> bool:
    return "@" in handler or "::" in handler or "\\" in handler or "Controller" in handler


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
    lines = content.splitlines()
    for line_no, line in enumerate(lines, start=1):
        if match := JS_FUNCTION_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "function", line_no, line.strip()))
        if match := JS_CONST_RE.match(line):
            symbols.append(ExtractedSymbol(match.group(1), "constant", line_no, line.strip()))
        if match := JS_CLASS_RE.search(line):
            symbols.append(ExtractedSymbol(match.group(1), "class", line_no, line.strip()))
        if match := JS_ROUTE_RE.search(line):
            route = _normalize_route_path(match.group("path"))
            symbols.append(ExtractedSymbol(route, "route", line_no, line.strip()))
            if match.group("handler"):
                relations.append(ExtractedRelation("route_to_handler", "symbol_name", match.group("handler"), line_no, 0.65))
        if JS_FASTIFY_ROUTE_RE.search(line):
            block = "\n".join(lines[line_no - 1 : min(line_no + 8, len(lines))])
            method_match = JS_OBJECT_METHOD_RE.search(block)
            path_match = JS_OBJECT_URL_RE.search(block)
            handler_match = JS_OBJECT_HANDLER_RE.search(block)
            if path_match:
                method = method_match.group("method") if method_match else "ROUTE"
                route = _normalize_route_path(path_match.group("path"))
                symbols.append(ExtractedSymbol(route, "route", line_no, f"{method} {route}"))
                if handler_match:
                    relations.append(ExtractedRelation("route_to_handler", "symbol_name", handler_match.group("handler"), line_no, 0.65))
        for pattern in (JS_IMPORT_RE, JS_SIDE_EFFECT_IMPORT_RE, JS_REQUIRE_RE):
            if match := pattern.search(line):
                relations.append(ExtractedRelation("imports", "module", match.group(1), line_no, 0.75))
        for call_name in _js_calls_in_line(line):
            relations.append(ExtractedRelation("calls", "symbol_name", call_name, line_no, 0.45))
    return symbols, relations


def _js_calls_in_line(line: str) -> list[str]:
    cleaned = re.sub(r"""(["'`]).*?\1""", '""', line)
    calls: list[str] = []
    for match in JS_CALL_RE.finditer(cleaned):
        name = match.group(1)
        if name in JS_CALL_EXCLUDES or name[0].isupper():
            continue
        if name not in calls:
            calls.append(name)
    return calls


def _sql_tables_in_text(text: str) -> list[str]:
    tables: list[str] = []
    for match in SQL_TABLE_RE.finditer(text):
        table = match.group(1).strip(".")
        if table and table not in tables:
            tables.append(table)
    return tables


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
        if match := GIN_ROUTE_RE.search(line):
            route = _normalize_route_path(match.group("path"))
            symbols.append(ExtractedSymbol(route, "route", line_no, stripped))
            relations.append(ExtractedRelation("route_to_handler", "symbol_name", match.group("handler").split(".")[-1], line_no, 0.65))
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


def _normalize_route_path(path: str) -> str:
    cleaned = path.strip() or "/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned


def _handler_name(value: str) -> str | None:
    cleaned = value.strip().strip("[]").strip()
    if not cleaned:
        return None
    cleaned = cleaned.split("=>", 1)[0].strip()
    cleaned = cleaned.strip("'\"")
    if "::" in cleaned:
        cleaned = cleaned.rsplit("::", 1)[-1]
    if "@" in cleaned:
        cleaned = cleaned.rsplit("@", 1)[-1]
    match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)", cleaned)
    return match.group(1) if match else None
