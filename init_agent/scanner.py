"""Repository scanner that builds file, symbol and relation records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_detector import detect_language, detect_role
from .symbol_extractor import extract_symbols_and_relations
from .utils import iter_indexable_files, mtime_iso, read_text_safely, relative_path, sha256_file, utc_now


INDEX_VERSION = "4"


def scan_project(root: Path, store: Any) -> dict[str, int]:
    indexed_files = 0
    indexed_symbols = 0
    indexed_relations = 0
    indexed_paths: set[str] = set()

    for path in iter_project_files(root):
        try:
            indexed_paths.add(relative_path(path, root))
            summary = index_file(root, path, store)
            indexed_files += 1
            indexed_symbols += summary["symbols"]
            indexed_relations += summary["relations"]
        except OSError:
            continue

    removed_files = 0
    if hasattr(store, "file_hashes") and hasattr(store, "delete_file_by_path"):
        for rel_path in sorted(path for path in store.file_hashes() if path not in indexed_paths):
            store.delete_file_by_path(rel_path)
            removed_files += 1

    if hasattr(store, "rebuild_term_stats"):
        store.rebuild_term_stats()
    if hasattr(store, "set_meta"):
        store.set_meta("index_version", INDEX_VERSION)
    store.connection.commit()
    return {"files": indexed_files, "symbols": indexed_symbols, "relations": indexed_relations, "removed": removed_files}


def index_file(root: Path, path: Path, store: Any) -> dict[str, int | str]:
    rel_path = relative_path(path, root)
    stat = path.stat()
    language = detect_language(path)
    role = detect_role(path)
    content = read_text_safely(path)
    symbols, extracted_relations = extract_symbols_and_relations(content, language, rel_path)
    file_id = store.upsert_file(
        {
            "path": rel_path,
            "extension": path.suffix.lower(),
            "language": language,
            "role": role,
            "size": stat.st_size,
            "sha256": sha256_file(path),
            "modified_at": mtime_iso(path),
            "indexed_at": utc_now(),
        }
    )
    relations = [
        {
            "relation": "belongs_to_language",
            "target_type": "language",
            "target_id": language,
            "confidence": 1.0,
            "metadata": {},
        },
        {
            "relation": "has_role",
            "target_type": "role",
            "target_id": role,
            "confidence": 1.0,
            "metadata": {},
        },
    ]
    relations.extend(
        {
            "relation": relation.relation,
            "target_type": relation.target_type,
            "target_id": relation.target,
            "confidence": relation.confidence,
            "metadata": {"line": relation.line},
        }
        for relation in extracted_relations
    )
    store.replace_file_symbols_and_relations(
        file_id,
        [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "line": symbol.line,
                "signature": symbol.signature,
            }
            for symbol in symbols
        ],
        relations,
    )
    return {"path": rel_path, "symbols": len(symbols), "relations": len(relations) + len(symbols)}


def iter_project_files(root: Path) -> list[Path]:
    return iter_indexable_files(root)
