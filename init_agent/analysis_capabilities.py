"""Persist the analysis capabilities actually available for each indexed file."""
from __future__ import annotations

import ast
import json
from typing import Any

CAPABILITY_SCHEMA_VERSION = 1
ANALYZER_VERSIONS = {
    "python": "python-ast-or-regex-v1",
    "php": "php-tree-sitter-or-regex-v1",
    "javascript": "regex-v1",
    "typescript": "regex-v1",
    "go": "regex-v1",
    "rust": "regex-v1",
}


def ensure_table(store: Any) -> None:
    store.connection.execute(
        "CREATE TABLE IF NOT EXISTS file_analysis ("
        "file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE, "
        "metadata_json TEXT NOT NULL)"
    )


def analyzer_fingerprint(language: str) -> str:
    return f"{language}:{ANALYZER_VERSIONS.get(language, 'regex-v1')}"


def current_fingerprint(language: str) -> str:
    """Return the configured analyzer identity used for invalidation."""
    return analyzer_fingerprint(language)


def build_capabilities(language: str, content: str, symbols: list[Any],
                       relations: list[Any], errors: list[str] | None = None) -> dict[str, Any]:
    errors = list(errors or [])
    analyzer = "regex"
    structural = False
    if language == "python":
        try:
            ast.parse(content)
            analyzer, structural = "python-ast", True
        except SyntaxError:
            analyzer = "python-regex-fallback"
            errors.append("Python syntax error; regex extraction used")
        except Exception as exc:
            analyzer = "python-regex-fallback"
            errors.append(f"Python AST unavailable: {type(exc).__name__}")
    elif language == "php":
        try:
            from .native_parser import extract_php_isolated
            extract_php_isolated(content)
            analyzer, structural = "php-tree-sitter", True
        except ImportError:
            analyzer = "php-regex-fallback"
            errors.append("optional PHP structural parser unavailable; regex extraction used")
        except Exception as exc:
            analyzer = "php-regex-fallback"
            errors.append(f"structural parser unavailable: {type(exc).__name__}")

    calls = sum(1 for relation in relations if relation.relation == "calls")
    imports = sum(1 for relation in relations if relation.relation in {
        "imports", "import", "include", "include_once", "require", "require_once"
    })
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "analyzer": analyzer,
        "analyzer_fingerprint": analyzer_fingerprint(language),
        "indexed": True,
        "text_search": True,
        "structural": structural,
        "symbols": len(symbols),
        "call_contexts": calls,
        "imports": imports,
        "errors": errors[:20],
        "partial": bool(errors),
    }


def save_capabilities(store: Any, file_id: int, metadata: dict[str, Any]) -> None:
    ensure_table(store)
    store.connection.execute(
        "INSERT INTO file_analysis(file_id, metadata_json) VALUES(?, ?) "
        "ON CONFLICT(file_id) DO UPDATE SET metadata_json=excluded.metadata_json",
        (file_id, json.dumps(metadata, sort_keys=True, separators=(",", ":"))),
    )


def load_capabilities(store: Any) -> dict[str, dict[str, Any]]:
    ensure_table(store)
    result: dict[str, dict[str, Any]] = {}
    rows = store.connection.execute(
        "SELECT files.path, files.language, file_analysis.metadata_json "
        "FROM files LEFT JOIN file_analysis ON file_analysis.file_id=files.id"
    ).fetchall()
    for row in rows:
        try:
            value = json.loads(row["metadata_json"] or "{}")
        except (TypeError, ValueError):
            value = {}
        value.setdefault("analyzer_fingerprint", "")
        result[row["path"]] = value
    return result
