"""Investigation path tracing over the local project graph."""

from __future__ import annotations

import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from .overview import build_overview_pack
from .utils import db_path


STRUCTURAL_FILE_RELATIONS = {
    "include",
    "include_once",
    "require",
    "require_once",
}
RENDER_TOKENS = {
    "frontend",
    "front",
    "view",
    "render",
    "rendering",
    "html",
    "markup",
    "template",
    "page",
    "pagina",
    "visualizzazione",
    "titolo",
    "title",
    "heading",
}
QUERY_STOPWORDS = {
    "a",
    "ad",
    "al",
    "alla",
    "allo",
    "anche",
    "bug",
    "che",
    "con",
    "da",
    "dal",
    "dei",
    "del",
    "fix",
    "errore",
    "error",
    "issue",
    "problem",
    "problema",
    "non",
    "di",
    "e",
    "il",
    "in",
    "la",
    "lo",
    "nel",
    "nella",
    "un",
    "una",
    "the",
    "and",
    "for",
    "from",
    "how",
    "is",
    "of",
    "to",
    "with",
    "della",
    "dello",
    "delle",
    "come",
    "viene",
}


def trace_query(root: Path, query: str, limit: int = 10, max_depth: int = 4) -> dict[str, Any]:
    """Return likely investigation paths for a task.

    This is intentionally conservative: it favors entrypoint-to-file traversal
    through structural relations such as PHP include/require and resolved
    imports. It is a follow-up orientation view, not a replacement for direct
    file verification.
    """

    bounded_limit = max(1, min(limit, 30))
    bounded_depth = max(1, min(max_depth, 6))
    database = db_path(root)
    if not database.exists():
        return {
            "query": query,
            "profile": "entrypoint_trace",
            "starts": [],
            "paths": [],
            "suggested_first_reads": [],
            "warnings": [f"index not found: {database}"],
        }
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        files = {int(row["id"]): dict(row) for row in conn.execute("SELECT * FROM files")}
        if not files:
            return {
                "query": query,
                "profile": "entrypoint_trace",
                "starts": [],
                "paths": [],
                "suggested_first_reads": [],
                "warnings": ["index has no files"],
            }
        path_to_id = {str(row["path"]): file_id for file_id, row in files.items()}
        symbols = _symbol_definitions(conn)
        graph = _build_graph(conn, files, path_to_id, symbols)

    tokens = _query_tokens(query)
    starts = _start_files(root, files, tokens)
    paths: list[dict[str, Any]] = []
    for start in starts:
        paths.extend(_trace_from(root, start, graph, files, tokens, bounded_depth))
    paths.sort(key=lambda item: item["score"], reverse=True)
    deduped = _dedupe_targets(paths)[:bounded_limit]
    return {
        "query": query,
        "profile": _profile_for_query(tokens),
        "starts": [_compact_file(files[file_id]) for file_id in starts],
        "paths": deduped,
        "suggested_first_reads": [item["target"] for item in deduped[:5]],
        "warnings": [],
    }


def _symbol_definitions(conn: sqlite3.Connection) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    for row in conn.execute("SELECT file_id, name FROM symbols"):
        result.setdefault(str(row["name"]).lower(), set()).add(int(row["file_id"]))
    return result


def _build_graph(
    conn: sqlite3.Connection,
    files: dict[int, dict[str, Any]],
    path_to_id: dict[str, int],
    symbols: dict[str, set[int]],
) -> dict[int, list[dict[str, Any]]]:
    graph: dict[int, list[dict[str, Any]]] = {}
    for row in conn.execute(
        "SELECT source_id, relation, target_type, target_id, confidence "
        "FROM relations WHERE source_type = 'file'"
    ):
        source = int(row["source_id"])
        relation = str(row["relation"])
        target_type = str(row["target_type"])
        target_id = str(row["target_id"])
        targets: set[int] = set()
        if target_type == "file" and relation in STRUCTURAL_FILE_RELATIONS:
            resolved = _resolve_path(str(files[source]["path"]), target_id, path_to_id)
            if resolved is not None:
                targets.add(resolved)
        elif target_type == "module" and relation == "imports":
            resolved = _resolve_module(target_id, path_to_id, str(files[source]["path"]))
            if resolved is not None:
                targets.add(resolved)
        elif target_type == "template" and relation == "renders_template":
            resolved = _resolve_template(target_id, path_to_id)
            if resolved is not None:
                targets.add(resolved)
        elif target_type == "symbol_name" and relation in {"calls", "route_to_handler"}:
            targets.update(symbols.get(target_id.lower(), set()))
        for target in targets:
            if target != source:
                graph.setdefault(source, []).append(
                    {
                        "target": target,
                        "relation": relation,
                        "target_id": target_id,
                        "confidence": float(row["confidence"] or 0.0),
                    }
                )
    return graph


def _resolve_path(source_path: str, target: str, path_to_id: dict[str, int]) -> int | None:
    normalized = target.lstrip("/")
    source_dir = Path(source_path).parent
    candidates = [
        normalized,
        str(source_dir / normalized),
        str(source_dir / Path(normalized).name),
    ]
    for candidate in candidates:
        clean = Path(candidate).as_posix().lstrip("./")
        if clean in path_to_id:
            return path_to_id[clean]
    return None


def _resolve_module(module: str, path_to_id: dict[str, int], source_path: str = "") -> int | None:
    if module.startswith("."):
        resolved = _resolve_relative_module(module, source_path, path_to_id)
        if resolved is not None:
            return resolved
    base = module.replace(".", "/")
    for candidate in (
        f"{base}.py",
        f"{base}/__init__.py",
        f"src/{base}.py",
        f"src/{base}/__init__.py",
    ):
        if candidate in path_to_id:
            return path_to_id[candidate]
    return None


def _resolve_relative_module(module: str, source_path: str, path_to_id: dict[str, int]) -> int | None:
    source_dir = Path(source_path).parent
    module_path = module
    while module_path.startswith("../"):
        source_dir = source_dir.parent
        module_path = module_path[3:]
    if module_path.startswith("./"):
        module_path = module_path[2:]
    base = source_dir / module_path
    candidates: list[str] = []
    for suffix in (".py", ".js", ".jsx", ".ts", ".tsx"):
        candidates.append(f"{base.as_posix()}{suffix}")
    for suffix in (".py", ".js", ".jsx", ".ts", ".tsx"):
        candidates.append((base / f"index{suffix}").as_posix())
    for candidate in candidates:
        if candidate in path_to_id:
            return path_to_id[candidate]
    return None


def _resolve_template(template: str, path_to_id: dict[str, int]) -> int | None:
    candidates = [
        template,
        f"templates/{template}",
    ]
    if "/" in template:
        app, rest = template.split("/", 1)
        candidates.append(f"{app}/templates/{app}/{rest}")
    for candidate in candidates:
        if candidate in path_to_id:
            return path_to_id[candidate]
    for path, file_id in path_to_id.items():
        if path.endswith(f"/templates/{template}") or path.endswith(f"/templates/{template.lstrip('/')}"):
            return file_id
    return None


def _start_files(root: Path, files: dict[int, dict[str, Any]], tokens: set[str]) -> list[int]:
    query_starts = _query_start_files(root, files, tokens)
    entry_starts = _overview_entrypoints(root, files)
    starts = [*query_starts, *entry_starts]
    return list(dict.fromkeys(starts))[:8]


def _query_start_files(root: Path, files: dict[int, dict[str, Any]], tokens: set[str]) -> list[int]:
    strong_tokens = {token for token in tokens if len(token) >= 8 or "test" in token}
    wants_tests = any("test" in token for token in tokens)
    wants_docs = bool(tokens & {"doc", "docs", "documentazione", "readme"})
    scored: list[tuple[float, int]] = []
    for file_id, item in files.items():
        path = str(item["path"])
        try:
            text = (root / path).read_text(errors="ignore").lower()
        except OSError:
            text = ""
        score = 0.0
        for token in strong_tokens:
            if token in path.lower():
                score += 4.0
            if token in text:
                score += 2.0
        score += _role_bias(str(item.get("role") or ""), path, wants_tests=wants_tests, wants_docs=wants_docs)
        if score:
            scored.append((score, file_id))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [file_id for _, file_id in scored[:4]]


def _overview_entrypoints(root: Path, files: dict[int, dict[str, Any]]) -> list[int]:
    path_to_id = {str(item["path"]): file_id for file_id, item in files.items()}
    result: list[int] = []
    try:
        overview = build_overview_pack(root)
    except Exception:
        overview = {}
    for item in overview.get("entry_points", [])[:4]:
        path = str(item.get("path") or "")
        if path in path_to_id:
            result.append(path_to_id[path])
    if result:
        return result
    scored: list[tuple[int, int]] = []
    for file_id, item in files.items():
        name = Path(str(item["path"])).name.lower()
        score = 0
        if name in {"index.php", "main.py", "__main__.py", "app.py", "server.py", "main.ts", "main.tsx", "main.rs"}:
            score += 10
        if item.get("role") == "route":
            score += 4
        if score:
            scored.append((score, file_id))
    scored.sort(reverse=True)
    return [file_id for _, file_id in scored[:6]]


def _trace_from(
    root: Path,
    start: int,
    graph: dict[int, list[dict[str, Any]]],
    files: dict[int, dict[str, Any]],
    tokens: set[str],
    max_depth: int,
) -> list[dict[str, Any]]:
    queue = deque([(start, [start], [])])
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, ...]] = set()
    while queue:
        current, path, edges = queue.popleft()
        state = tuple(path)
        if state in seen:
            continue
        seen.add(state)
        score, reasons = _file_score(root, str(files[current]["path"]), tokens, len(path) - 1)
        if score > 0:
            results.append(
                {
                    "target": str(files[current]["path"]),
                    "score": round(score, 3),
                    "distance": len(path) - 1,
                    "path": [str(files[item]["path"]) for item in path],
                    "edges": edges,
                    "reasons": reasons,
                }
            )
        if len(path) - 1 >= max_depth:
            continue
        for edge in _bounded_neighbors(graph.get(current, [])):
            target = int(edge["target"])
            if target in path:
                continue
            queue.append((target, [*path, target], [*edges, str(edge["relation"])]))
    return results


def _bounded_neighbors(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def weight(edge: dict[str, Any]) -> float:
        relation = str(edge["relation"])
        base = 4.0 if relation in STRUCTURAL_FILE_RELATIONS else 2.0 if relation == "imports" else 1.0
        return base + float(edge.get("confidence") or 0.0)

    return sorted(edges, key=weight, reverse=True)[:25]


def _file_score(root: Path, path: str, tokens: set[str], distance: int) -> tuple[float, list[str]]:
    try:
        text = (root / path).read_text(errors="ignore").lower()
    except OSError:
        text = ""
    score = max(0.1, 3.0 - distance * 0.35)
    reasons = [f"reachable from start at distance {distance}"]
    basename = Path(path).name.lower()
    lower_path = path.lower()
    for token in sorted(tokens):
        if token in lower_path:
            score += 4.0
            reasons.append(f'path contains "{token}"')
        if token in text:
            score += 2.0
            reasons.append(f'content contains "{token}"')
        elif token in basename:
            score += 1.5
            reasons.append(f'filename contains "{token}"')
    score += _path_bias(path, text, tokens)
    if _emits_markup(text):
        score += 2.0
        reasons.append("emits HTML/render markup")
    return max(0.0, score), reasons[:8]


def _role_bias(role: str, path: str, *, wants_tests: bool, wants_docs: bool) -> float:
    lower_path = path.lower()
    score = 0.0
    if role == "test":
        score += 2.0 if wants_tests else -4.0
    if role == "documentation" or lower_path.endswith((".md", ".rst")):
        score += 1.0 if wants_docs else -3.0
    if "/versions/" in lower_path or lower_path.startswith("alembic/") or "/migrations/" in lower_path:
        score -= 3.0
    if lower_path.endswith((".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        score -= 4.0
    return score


def _path_bias(path: str, text: str, tokens: set[str]) -> float:
    lower_path = path.lower()
    wants_tests = any("test" in token for token in tokens)
    wants_docs = bool(tokens & {"doc", "docs", "documentazione", "readme"})
    score = _role_bias(_role_from_path(lower_path), lower_path, wants_tests=wants_tests, wants_docs=wants_docs)
    if any(word in lower_path for word in ("/orchestrator", "/controller", "/handler", "/router", "/service")):
        score += 1.0
    if re.search(r"\b(handle|process|dispatch|orchestrat|route|persist|create)_?[a-z_]*\b", text):
        score += 0.75
    return score


def _role_from_path(path: str) -> str:
    if "/test" in path or path.startswith("test") or path.startswith("tests/"):
        return "test"
    if path.endswith((".md", ".rst")):
        return "documentation"
    return ""


def _emits_markup(text: str) -> bool:
    return bool(re.search(r"<h[1-6]\b|echo\s+['\"]<|<main\b|<title\b|render\(|template", text))


def _dedupe_targets(paths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for item in paths:
        target = str(item["target"])
        if target in positions:
            existing_index = positions[target]
            existing = result[existing_index]
            if not existing.get("edges") and item.get("edges"):
                result[existing_index] = item
            continue
        positions[target] = len(result)
        result.append(item)
    return result


def _query_tokens(query: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", query.lower())
        if len(token) > 1 and token not in QUERY_STOPWORDS
    }
    return tokens


def _profile_for_query(tokens: set[str]) -> str:
    if tokens & RENDER_TOKENS:
        return "entrypoint_render"
    if any("test" in token for token in tokens):
        return "test_trace"
    return "entrypoint_trace"


def _compact_file(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": item.get("path", ""),
        "language": item.get("language", ""),
        "role": item.get("role", ""),
    }
