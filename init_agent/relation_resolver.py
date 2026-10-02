"""Resolve extracted relation names into concrete repository files."""

from __future__ import annotations

import json
import posixpath
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any
from .repo_budget import WorkBudgetExceeded, bounded_write, budgeted, checkpoint


RESOLVED_TARGET_TYPE = "resolved_file"
RESOLVED_SYMBOL_TARGET_TYPE = "resolved_symbol"
RESOLVABLE_RELATIONS = {
    "include",
    "include_once",
    "require",
    "require_once",
    "imports",
    "imports_symbol",
    "calls",
    "route_to_handler",
    "renders_template",
}


@bounded_write
def rebuild_resolved_relations(store: Any) -> dict[str, int]:
    """Rebuild concrete file edges from the current raw graph.

    Raw extracted relations stay intact. Resolved edges use a distinct target
    type so refreshes can replace them without reparsing source files.
    """

    connection = store.connection
    connection.execute("DELETE FROM relations WHERE target_type = ?", (RESOLVED_TARGET_TYPE,))
    connection.execute("DELETE FROM relations WHERE target_type = ?", (RESOLVED_SYMBOL_TARGET_TYPE,))
    files = {
        int(row["id"]): {
            "path": str(row["path"]),
            "language": str(row["language"] or ""),
        }
        for row in budgeted(connection.execute("SELECT id, path, language FROM files"))
    }
    path_to_id = {item["path"]: file_id for file_id, item in budgeted(files.items())}
    module_index = _module_index(path_to_id)
    module_cache: dict[tuple[str, str, str], list[int]] = {}
    template_cache: dict[str, list[int]] = {}
    symbols_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    symbols_by_file: dict[int, set[str]] = defaultdict(set)
    symbol_by_id: dict[int, dict[str, Any]] = {}
    for row in connection.execute(
        "SELECT id, file_id, name, kind, qualified_name, container_name FROM symbols"
    ):
        checkpoint()
        item = {
            "id": int(row["id"]),
            "file_id": int(row["file_id"]),
            "name": str(row["name"]),
            "kind": str(row["kind"]),
            "qualified_name": str(row["qualified_name"] or row["name"]),
            "container_name": str(row["container_name"] or ""),
        }
        symbols_by_name[item["name"].lower()].append(item)
        symbols_by_file[item["file_id"]].add(item["name"].lower())
        symbol_by_id[item["id"]] = item
    raw_relations = [
        dict(row)
        for row in budgeted(connection.execute(
            """
            SELECT id, source_id, relation, target_type, target_id, confidence, metadata_json
            FROM relations
            WHERE source_type = 'file' AND target_type != ?
            ORDER BY id
            """,
            (RESOLVED_TARGET_TYPE,),
        ))
        if str(row["relation"]) in RESOLVABLE_RELATIONS
    ]

    records: dict[tuple[int, str, str], dict[str, Any]] = {}
    resolved_raw_ids: set[int] = set()
    ambiguous_raw_ids: set[int] = set()
    module_bindings: dict[int, dict[str, int]] = defaultdict(dict)
    symbol_bindings: dict[int, dict[str, tuple[int, str]]] = defaultdict(dict)

    def module_candidates(source_path: str, language: str, module: str) -> list[int]:
        key = (source_path, language, module)
        if key not in module_cache:
            module_cache[key] = _module_candidates(source_path, language, module, path_to_id, module_index)
        return module_cache[key]

    def template_candidates(template: str) -> list[int]:
        if template not in template_cache:
            template_cache[template] = _template_candidates(template, path_to_id)
        return template_cache[template]

    def add(
        row: dict[str, Any],
        target_file_id: int,
        resolver: str,
        confidence: float,
        resolved_symbol_name: str = "",
    ) -> None:
        source_id = int(row["source_id"])
        target_path = files[target_file_id]["path"]
        metadata = _metadata(row)
        metadata.update(
            {
                "resolved": True,
                "resolver": resolver,
                "raw_relation_id": int(row["id"]),
                "raw_target_type": str(row["target_type"]),
                "raw_target_id": str(row["target_id"]),
            }
        )
        if resolved_symbol_name:
            metadata["resolved_symbol_name"] = resolved_symbol_name
        key = (source_id, str(row["relation"]), target_path)
        candidate = {
            "source_id": source_id,
            "relation": str(row["relation"]),
            "target_id": target_path,
            "confidence": round(min(1.0, max(0.0, confidence)), 3),
            "metadata": metadata,
        }
        existing = records.get(key)
        if existing is None:
            checkpoint("records")
        if existing is None or float(candidate["confidence"]) > float(existing["confidence"]):
            records[key] = candidate
        resolved_raw_ids.add(int(row["id"]))

    # Resolve direct file/module/template edges first. Their targets provide
    # scope for the subsequent symbol-call pass.
    for row in raw_relations:
        checkpoint()
        source_id = int(row["source_id"])
        source = files.get(source_id)
        if source is None:
            continue
        relation = str(row["relation"])
        target_type = str(row["target_type"])
        target = str(row["target_id"])
        candidates: list[int] = []
        resolver = ""
        if target_type == "file" and relation in {"include", "include_once", "require", "require_once"}:
            candidates = _path_candidates(source["path"], target, path_to_id)
            resolver = "relative_file"
        elif target_type == "module" and relation == "imports":
            candidates = module_candidates(source["path"], source["language"], target)
            resolver = "module_import"
        elif target_type == "template" and relation == "renders_template":
            candidates = template_candidates(target)
            resolver = "template_path"
        if len(candidates) == 1:
            target_file_id = candidates[0]
            add(row, target_file_id, resolver, float(row.get("confidence") or 0.0) + 0.15)
            if relation == "imports":
                local_name = str(_metadata(row).get("local_name") or target.split(".")[0]).lower()
                module_bindings[source_id][local_name] = target_file_id
        elif len(candidates) > 1:
            ambiguous_raw_ids.add(int(row["id"]))

    # Resolve imported symbol bindings after module targets are known.
    for row in raw_relations:
        checkpoint()
        if str(row["relation"]) != "imports_symbol" or str(row["target_type"]) != "symbol_name":
            continue
        source_id = int(row["source_id"])
        source = files.get(source_id)
        if source is None:
            continue
        metadata = _metadata(row)
        module = str(metadata.get("module") or "")
        imported_name = str(metadata.get("imported_name") or row["target_id"])
        local_name = str(metadata.get("local_name") or imported_name)
        candidates = module_candidates(source["path"], source["language"], module)
        if not candidates and module:
            candidates = module_candidates(source["path"], source["language"], f"{module}.{imported_name}")
        candidates = [
            file_id
            for file_id in budgeted(candidates)
            if imported_name.lower() in symbols_by_file.get(file_id, set())
            or files[file_id]["path"].endswith(f"/{imported_name}.py")
        ]
        candidates = _unique(candidates)
        if len(candidates) == 1:
            target_file_id = candidates[0]
            symbol_bindings[source_id][local_name.lower()] = (target_file_id, imported_name.lower())
            module_bindings[source_id].setdefault(local_name.lower(), target_file_id)
            add(row, target_file_id, "imported_symbol", float(row.get("confidence") or 0.0) + 0.15)
        elif len(candidates) > 1:
            ambiguous_raw_ids.add(int(row["id"]))

    include_components = _include_components(records, path_to_id)
    for row in raw_relations:
        checkpoint()
        relation = str(row["relation"])
        if relation not in {"calls", "route_to_handler"} or str(row["target_type"]) != "symbol_name":
            continue
        source_id = int(row["source_id"])
        source = files.get(source_id)
        if source is None:
            continue
        raw_name = str(row["target_id"])
        metadata = _metadata(row)
        qualified = str(metadata.get("qualified_name") or raw_name)
        target_name = raw_name.rsplit(".", 1)[-1].lower()
        candidate_ids: list[int] = []
        resolver = ""
        resolved_symbol_name = target_name
        qualifier = qualified.split(".", 1)[0].lower() if "." in qualified else ""
        if (
            relation == "calls"
            and source["language"] == "python"
            and qualifier
            and qualifier not in module_bindings[source_id]
        ):
            continue

        if target_name in symbols_by_file.get(source_id, set()):
            candidate_ids = [source_id]
            resolver = "same_file_symbol"
        else:
            binding = symbol_bindings[source_id].get(qualified.lower()) or symbol_bindings[source_id].get(target_name)
            if binding is not None:
                candidate_ids = [binding[0]]
                resolved_symbol_name = binding[1]
                resolver = "imported_symbol_call"
            else:
                bound_file_id = module_bindings[source_id].get(qualifier)
                if bound_file_id is not None and target_name in symbols_by_file.get(bound_file_id, set()):
                    candidate_ids = [bound_file_id]
                    resolver = "qualified_module_call"
                else:
                    imported_targets = {
                        target_file_id
                        for target_file_id in budgeted(module_bindings[source_id].values())
                        if target_name in symbols_by_file.get(target_file_id, set())
                    }
                    if len(imported_targets) == 1:
                        candidate_ids = list(imported_targets)
                        resolver = "import_scope_call"

        if not candidate_ids and source["language"] == "php":
            source_component = include_components.get(source_id)
            same_language = [
                int(item["file_id"])
                for item in budgeted(symbols_by_name.get(target_name, []))
                if files.get(int(item["file_id"]), {}).get("language") == "php"
                and source_component is not None
                and include_components.get(int(item["file_id"])) == source_component
            ]
            same_language = _unique(same_language)
            if len(same_language) == 1:
                candidate_ids = same_language
                resolver = "unique_php_symbol"

        candidate_ids = _unique(candidate_ids)
        if len(candidate_ids) == 1:
            bonus = 0.35 if resolver in {"same_file_symbol", "imported_symbol_call", "qualified_module_call"} else 0.2
            add(
                row,
                candidate_ids[0],
                resolver,
                float(row.get("confidence") or 0.0) + bonus,
                resolved_symbol_name=resolved_symbol_name,
            )
        elif len(candidate_ids) > 1:
            ambiguous_raw_ids.add(int(row["id"]))

    connection.executemany(
        """
        INSERT INTO relations(source_type, source_id, relation, target_type, target_id, confidence, metadata_json)
        VALUES('file', ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                item["source_id"],
                item["relation"],
                RESOLVED_TARGET_TYPE,
                item["target_id"],
                item["confidence"],
                json.dumps(item["metadata"], sort_keys=True),
            )
            for item in budgeted(records.values())
        ),
    )
    symbol_stats = _rebuild_resolved_symbol_relations(
        connection,
        files,
        path_to_id,
        symbol_by_id,
        symbols_by_name,
        module_bindings,
        symbol_bindings,
        include_components,
        records,
    )
    stats = {
        "resolvable_relations": len(raw_relations),
        "resolved_relations": len(resolved_raw_ids),
        "resolved_file_edges": len(records) + int(symbol_stats.get("symbol_derived_file_edges", 0)),
        "direct_resolved_file_edges": len(records),
        "ambiguous_relations": len(ambiguous_raw_ids - resolved_raw_ids),
        **symbol_stats,
    }
    store.set_meta("resolved_relation_stats", stats)
    return stats


def _rebuild_resolved_symbol_relations(
    connection: Any,
    files: dict[int, dict[str, str]],
    path_to_id: dict[str, int],
    symbol_by_id: dict[int, dict[str, Any]],
    symbols_by_name: dict[str, list[dict[str, Any]]],
    module_bindings: dict[int, dict[str, int]],
    symbol_bindings: dict[int, dict[str, tuple[int, str]]],
    include_components: dict[int, int],
    file_records: dict[tuple[int, str, str], dict[str, Any]],
) -> dict[str, int]:
    raw_rows = []
    for row in connection.execute(
        """
        SELECT id, source_id, relation, target_type, target_id, context_symbol_id,
               confidence, metadata_json
        FROM relations
        WHERE source_type = 'file'
          AND target_type = 'symbol_name'
          AND relation IN ('calls', 'inherits', 'implements')
        ORDER BY id
        """
    ):
        checkpoint()
        item = dict(row)
        if item.get("context_symbol_id") is not None:
            raw_rows.append(item)
    class_ids_by_file_qualified: dict[tuple[int, str], list[int]] = defaultdict(list)
    for symbol in symbol_by_id.values():
        checkpoint()
        if str(symbol["kind"]) == "class":
            class_ids_by_file_qualified[
                (int(symbol["file_id"]), str(symbol["qualified_name"]))
            ].append(int(symbol["id"]))
    file_targets: dict[tuple[int, str, str], set[int]] = defaultdict(set)
    for item in file_records.values():
        checkpoint()
        metadata = dict(item.get("metadata") or {})
        raw_target = str(metadata.get("raw_target_id") or "").lower()
        target_file_id = path_to_id.get(str(item["target_id"]))
        if raw_target and target_file_id is not None:
            file_targets[(int(item["source_id"]), str(item["relation"]), raw_target)].add(target_file_id)

    resolved: dict[tuple[int, str, int], dict[str, Any]] = {}
    parent_symbol_ids: dict[int, set[int]] = defaultdict(set)
    ambiguous = 0
    raw_rows.sort(key=lambda item: 0 if str(item["relation"]) in {"inherits", "implements"} else 1)
    for row in raw_rows:
        checkpoint()
        metadata = _metadata(row)
        source_file_id = int(row["source_id"])
        source_symbol = symbol_by_id.get(int(row["context_symbol_id"]))
        if source_symbol is None:
            continue
        source_file = files.get(source_file_id)
        if source_file is None:
            continue
        relation = str(row["relation"])
        raw_name = str(row["target_id"])
        target_name = raw_name.rsplit(".", 1)[-1].rsplit("\\", 1)[-1].lower()
        qualified = str(metadata.get("qualified_name") or raw_name)
        candidate_ids: list[int] = []
        resolver = ""
        receiver_scoped = False
        receiver = qualified.split(".", 1)[0].lower() if "." in qualified else ""

        if relation == "calls" and source_file["language"] == "python":
            if receiver in {"self", "cls", "super"}:
                receiver_scoped = True
                candidate_ids = _python_receiver_method_ids(
                    symbols_by_name,
                    symbol_by_id,
                    class_ids_by_file_qualified,
                    source_symbol,
                    target_name,
                    parent_symbol_ids,
                    include_current=receiver != "super",
                )
                resolver = f"python_{receiver}_method"
            elif receiver and receiver not in module_bindings[source_file_id]:
                continue

        if not receiver_scoped:
            same_file = _symbol_ids_for_name(symbols_by_name, target_name, {source_file_id}, relation)
            if len(same_file) == 1:
                candidate_ids = same_file
                resolver = "same_file_symbol"

        if not candidate_ids and not receiver_scoped:
            binding = symbol_bindings[source_file_id].get(qualified.lower()) or symbol_bindings[source_file_id].get(target_name)
            if binding is not None:
                candidate_ids = _symbol_ids_for_name(symbols_by_name, binding[1], {binding[0]}, relation)
                resolver = "imported_symbol"
            if not candidate_ids:
                qualifier = qualified.split(".", 1)[0].lower() if "." in qualified else ""
                bound_file_id = module_bindings[source_file_id].get(qualifier)
                if bound_file_id is not None:
                    candidate_ids = _symbol_ids_for_name(symbols_by_name, target_name, {bound_file_id}, relation)
                    resolver = "qualified_module_symbol"
            if not candidate_ids and relation == "calls":
                target_files = file_targets.get((source_file_id, relation, raw_name.lower()), set())
                candidate_ids = _symbol_ids_for_name(symbols_by_name, target_name, target_files, relation)
                if candidate_ids:
                    resolver = "resolved_file_symbol"
            if not candidate_ids and source_file["language"] == "php":
                component = include_components.get(source_file_id)
                target_files = {
                    int(item["file_id"])
                    for item in budgeted(symbols_by_name.get(target_name, []))
                    if component is not None and include_components.get(int(item["file_id"])) == component
                }
                candidate_ids = _symbol_ids_for_name(symbols_by_name, target_name, target_files, relation)
                if candidate_ids:
                    resolver = "php_include_scope_symbol"
            if not candidate_ids and relation in {"inherits", "implements"}:
                same_language = {
                    int(item["file_id"])
                    for item in budgeted(symbols_by_name.get(target_name, []))
                    if files.get(int(item["file_id"]), {}).get("language") == source_file["language"]
                }
                candidate_ids = _symbol_ids_for_name(symbols_by_name, target_name, same_language, relation)
                if len(candidate_ids) == 1:
                    resolver = "unique_language_type"

        candidate_ids = _unique(candidate_ids)
        if len(candidate_ids) != 1:
            if len(candidate_ids) > 1:
                ambiguous += 1
            continue
        target_symbol_id = candidate_ids[0]
        target_symbol = symbol_by_id[target_symbol_id]
        if relation in {"inherits", "implements"}:
            parent_symbol_ids[int(source_symbol["id"])].add(target_symbol_id)
        resolved_metadata = {
            **metadata,
            "resolved": True,
            "resolver": resolver,
            "provenance": "resolved",
            "raw_relation_id": int(row["id"]),
            "raw_target_id": raw_name,
            "source_qualified_name": source_symbol["qualified_name"],
            "target_path": files[int(target_symbol["file_id"])]["path"],
            "target_qualified_name": target_symbol["qualified_name"],
        }
        source_symbol_id = int(source_symbol["id"])
        key = (source_symbol_id, relation, target_symbol_id)
        confidence = min(1.0, float(row.get("confidence") or 0.0) + 0.15)
        candidate = {
            "source_id": source_symbol_id,
            "relation": relation,
            "target_id": target_symbol_id,
            "confidence": round(confidence, 3),
            "metadata": resolved_metadata,
        }
        existing = resolved.get(key)
        if existing is None:
            checkpoint("records")
        if existing is None or float(candidate["confidence"]) > float(existing["confidence"]):
            resolved[key] = candidate

    connection.executemany(
        """
        INSERT INTO relations(source_type, source_id, relation, target_type, target_id, confidence, metadata_json)
        VALUES('symbol', ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                item["source_id"],
                item["relation"],
                RESOLVED_SYMBOL_TARGET_TYPE,
                str(item["target_id"]),
                item["confidence"],
                json.dumps(item["metadata"], sort_keys=True),
            )
            for item in budgeted(resolved.values())
        ),
    )
    derived_file_edges: dict[tuple[int, str, str], dict[str, Any]] = {}
    for item in resolved.values():
        checkpoint()
        if item["relation"] not in {"inherits", "implements"}:
            continue
        source_symbol = symbol_by_id[int(item["source_id"])]
        target_symbol = symbol_by_id[int(item["target_id"])]
        source_file_id = int(source_symbol["file_id"])
        target_path = files[int(target_symbol["file_id"])]["path"]
        key = (source_file_id, str(item["relation"]), target_path)
        derived_file_edges[key] = {
            "source_id": source_file_id,
            "relation": item["relation"],
            "target_path": target_path,
            "confidence": item["confidence"],
            "metadata": {
                "resolved": True,
                "resolver": "resolved_symbol_type",
                "provenance": "resolved",
                "source_qualified_name": source_symbol["qualified_name"],
                "target_qualified_name": target_symbol["qualified_name"],
            },
        }
    connection.executemany(
        """
        INSERT INTO relations(source_type, source_id, relation, target_type, target_id, confidence, metadata_json)
        VALUES('file', ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                item["source_id"],
                item["relation"],
                RESOLVED_TARGET_TYPE,
                item["target_path"],
                item["confidence"],
                json.dumps(item["metadata"], sort_keys=True),
            )
            for item in budgeted(derived_file_edges.values())
        ),
    )
    return {
        "resolvable_symbol_relations": len(raw_rows),
        "resolved_symbol_edges": len(resolved),
        "ambiguous_symbol_relations": ambiguous,
        "symbol_derived_file_edges": len(derived_file_edges),
    }


def _symbol_ids_for_name(
    symbols_by_name: dict[str, list[dict[str, Any]]],
    name: str,
    file_ids: set[int],
    relation: str,
) -> list[int]:
    allowed_kinds = {"class", "interface", "trait", "enum"} if relation in {"inherits", "implements"} else {"function", "method"}
    return [
        int(item["id"])
        for item in budgeted(symbols_by_name.get(name.lower(), []))
        if int(item["file_id"]) in file_ids and str(item["kind"]) in allowed_kinds
    ]


def _python_receiver_method_ids(
    symbols_by_name: dict[str, list[dict[str, Any]]],
    symbol_by_id: dict[int, dict[str, Any]],
    class_ids_by_file_qualified: dict[tuple[int, str], list[int]],
    source_symbol: dict[str, Any],
    target_name: str,
    parent_symbol_ids: dict[int, set[int]],
    *,
    include_current: bool,
) -> list[int]:
    container_name = str(source_symbol.get("container_name") or "")
    if not container_name:
        return []
    class_ids = class_ids_by_file_qualified.get(
        (int(source_symbol["file_id"]), container_name),
        [],
    )
    if len(class_ids) != 1:
        return []

    current_class_id = class_ids[0]
    allowed_class_ids = {current_class_id} if include_current else set()
    pending = list(parent_symbol_ids.get(current_class_id, set()))
    while pending:
        checkpoint()
        class_id = pending.pop()
        if class_id in allowed_class_ids:
            continue
        allowed_class_ids.add(class_id)
        pending.extend(parent_symbol_ids.get(class_id, set()))

    allowed_containers = {
        str(symbol_by_id[class_id]["qualified_name"])
        for class_id in budgeted(allowed_class_ids)
        if class_id in symbol_by_id
    }
    return [
        int(item["id"])
        for item in budgeted(symbols_by_name.get(target_name.lower(), []))
        if str(item["kind"]) == "method"
        and str(item.get("container_name") or "") in allowed_containers
    ]


def _path_candidates(source_path: str, target: str, path_to_id: dict[str, int]) -> list[int]:
    clean_target = target.replace("\\", "/").strip().strip("\"'")
    clean_target = clean_target.removeprefix("/")
    source_dir = PurePosixPath(source_path).parent
    candidates = [clean_target, _normalize_path(source_dir / clean_target)]
    return _existing_candidates(candidates, path_to_id)


def _module_candidates(
    source_path: str,
    language: str,
    module: str,
    path_to_id: dict[str, int],
    module_index: dict[str, list[int]],
) -> list[int]:
    clean_module = module.strip()
    if not clean_module:
        return []
    if clean_module.startswith(("./", "../")):
        source_dir = PurePosixPath(source_path).parent
        base = _normalize_path(source_dir / clean_module)
        candidates = [
            f"{base}{suffix}"
            for suffix in budgeted((".py", ".js", ".jsx", ".ts", ".tsx", ".php"))
        ]
        candidates.extend(
            f"{base}/index{suffix}"
            for suffix in budgeted((".js", ".jsx", ".ts", ".tsx"))
        )
        return _existing_candidates(candidates, path_to_id)
    if language != "python":
        return []
    key = clean_module.lstrip(".")
    return list(module_index.get(key, []))


def _template_candidates(template: str, path_to_id: dict[str, int]) -> list[int]:
    clean = template.lstrip("/")
    candidates = [clean, f"templates/{clean}"]
    if "/" in clean:
        app, rest = clean.split("/", 1)
        candidates.append(f"{app}/templates/{app}/{rest}")
    exact = _existing_candidates(candidates, path_to_id)
    if exact:
        return exact
    return _unique(
        file_id
        for path, file_id in budgeted(path_to_id.items())
        if path.endswith(f"/templates/{clean}")
    )


def _module_index(path_to_id: dict[str, int]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = defaultdict(list)
    for path, file_id in path_to_id.items():
        checkpoint()
        if len(path) > 4096 or len(PurePosixPath(path).parts) > 64:
            raise WorkBudgetExceeded("repository path complexity limit exceeded; results are incomplete")
        if not path.endswith(".py"):
            continue
        parts = list(PurePosixPath(path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        for start in range(len(parts)):
            checkpoint()
            key = ".".join(parts[start:])
            if key and file_id not in index[key]:
                index[key].append(file_id)
    return dict(index)


def _existing_candidates(candidates: list[str], path_to_id: dict[str, int]) -> list[int]:
    return _unique(path_to_id[path] for path in budgeted(candidates) if path in path_to_id)


def _normalize_path(path: PurePosixPath | str) -> str:
    normalized = posixpath.normpath(PurePosixPath(path).as_posix())
    return "" if normalized == "." else normalized.removeprefix("./")


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(str(row.get("metadata_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _include_components(
    records: dict[tuple[int, str, str], dict[str, Any]],
    path_to_id: dict[str, int],
) -> dict[int, int]:
    parent: dict[int, int] = {}

    def find(value: int) -> int:
        parent.setdefault(value, value)
        while parent[value] != value:
            checkpoint()
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for item in records.values():
        checkpoint()
        if item["relation"] not in {"include", "include_once", "require", "require_once"}:
            continue
        target_id = path_to_id.get(str(item["target_id"]))
        if target_id is not None:
            union(int(item["source_id"]), target_id)
    return {file_id: find(file_id) for file_id in budgeted(parent)}


def _unique(values: Any) -> list[int]:
    return list(dict.fromkeys(int(value) for value in budgeted(values)))
