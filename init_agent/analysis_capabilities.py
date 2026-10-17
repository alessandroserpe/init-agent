"""Persist the analysis capabilities actually available for each indexed file."""
from __future__ import annotations

from functools import lru_cache
import importlib.metadata
import importlib.util
import json
import sys
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
    base = f"{language}:{ANALYZER_VERSIONS.get(language, 'regex-v1')}"
    if language == "typescript":
        from .typescript_analyzer import compiler_fingerprint
        return compiler_fingerprint()
    if language == "python":
        return f"{base}:py{sys.version_info.major}.{sys.version_info.minor}"
    if language == "php":
        return f"{base}:{_optional_package_fingerprint('tree_sitter', 'tree-sitter')}:{_optional_package_fingerprint('tree_sitter_php', 'tree-sitter-php')}"
    return base


@lru_cache(maxsize=4)
def _optional_package_fingerprint(module: str, distribution: str) -> str:
    try:
        available = importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        available = False
    if not available:
        return f"{module}=missing"
    try:
        version = importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        version = "unknown-version"
    return f"{module}={version}"


def current_fingerprint(language: str) -> str:
    """Return the configured analyzer identity used for invalidation."""
    return analyzer_fingerprint(language)


def build_capabilities(language: str, content: str, symbols: list[Any],
                       relations: list[Any], errors: list[str] | None = None) -> dict[str, Any]:
    errors = list(errors or [])
    from .symbol_extractor import last_analyzer_outcome
    outcome = last_analyzer_outcome()
    analyzer = outcome.split(":", 1)[0] if outcome != "regex" else "regex"
    structural = analyzer in {"python-ast", "php-tree-sitter"} and not errors
    if ":" in outcome:
        errors.append(outcome.split(":", 1)[1])
    if analyzer.endswith("regex-fallback") and not errors:
        errors.append("structural parser unavailable; regex extraction used")

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
