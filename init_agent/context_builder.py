"""Build compact context packs from the indexed project graph."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from math import log
from pathlib import Path
from typing import Any

from .feedback import feedback_signals
from .graph_store import GraphStore
from .text_tokens import is_query_noise_token, tokenize_query

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
TEST_AWARE_TOKENS = {"test", "tests", "unittest", "pytest", "coverage", "spec", "assertion", "fixture"}
SYMPTOM_QUERY_TOKENS = {
    "bug",
    "errore",
    "error",
    "exception",
    "fail",
    "fails",
    "failing",
    "failure",
    "regression",
    "regressione",
    "render",
    "rendered",
    "response",
    "risposta",
    "symptom",
    "sintomo",
    "test",
    "tests",
    "wrong",
}
GENERIC_SYMPTOM_PATH_TOKENS = {
    "base",
    "component",
    "controller",
    "handler",
    "http",
    "page",
    "request",
    "response",
    "route",
    "router",
    "template",
    "view",
    "views",
}
MAX_COMMIT_FILES = 10
UI_INTENT_TOKENS = {"css", "style", "stile", "layout", "design", "ui", "frontend", "colore", "colori"}
DB_INTENT_TOKENS = {"sql", "migration", "migrations", "database", "db", "tabella", "schema"}
DOCS_INTENT_TOKENS = {"readme", "docs", "documentazione", "guida"}
EXAMPLE_INTENT_TOKENS = {"example", "examples", "demo", "sample", "tutorial", "playground"}
ASSET_EXTENSIONS = {".css", ".scss", ".less"}
MIGRATION_EXTENSIONS = {".sql"}
DOCS_EXTENSIONS = {".md", ".rst", ".txt"}
SOURCE_BACKEND_EXTENSIONS = {".php", ".py", ".js", ".ts", ".go", ".rs"}
EXAMPLE_PATH_PARTS = {"example", "examples", "demo", "demos", "sample", "samples", "playground"}


def build_context_pack(root: Path, query: str) -> dict[str, Any]:
    tokens = _tokens(query)
    with GraphStore(root) as store:
        conn = store.connection
        files = [dict(row) for row in conn.execute("SELECT id, path, language, role FROM files")]
        symbols = [
            dict(row)
            for row in conn.execute(
                """
                SELECT s.id, s.name, s.kind, s.line, f.id AS file_id, f.path AS file, f.role AS file_role
                FROM symbols s
                JOIN files f ON f.id = s.file_id
                """
            )
        ]
        commits = [
            dict(row)
            for row in conn.execute(
                """
                SELECT c.id, c.hash, c.author, c.date, c.message, f.path
                FROM git_commits c
                LEFT JOIN git_commit_files f ON f.commit_id = c.id
                ORDER BY c.date DESC
                """
            )
        ]
        relations = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_id, relation, target_type, target_id, metadata_json
                FROM relations
                WHERE source_type = 'file'
                ORDER BY source_id, relation, target_type, target_id
                """
            )
        ]
        term_weights = _load_term_weights(conn, tokens)

    file_by_id = {int(item["id"]): item for item in files}
    token_weights = term_weights or _token_weights(tokens, files, symbols, commits)
    file_scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)

    _score_files_by_path_role_language(files, tokens, token_weights, file_scores, reasons)
    _score_files_by_symbols(symbols, tokens, token_weights, file_scores, reasons)
    query_commits = _score_files_by_commits(commits, tokens, token_weights, file_scores, reasons)
    _score_files_by_calls(relations, file_by_id, tokens, token_weights, file_scores, reasons)
    _score_related_files(relations, file_by_id, file_scores, reasons)
    _adjust_test_file_scores(files, tokens, file_scores, reasons)
    _adjust_role_type_scores(files, tokens, file_scores, reasons)
    _score_files_by_feedback(root, files, tokens, file_scores, reasons)

    raw_candidates = [
        {
            "path": item["path"],
            "raw_score": file_scores[item["path"]],
            "language": item["language"],
            "role": item["role"],
            "reasons": reasons[item["path"]][:8],
        }
        for item in files
        if file_scores[item["path"]] > 0
    ]
    raw_candidates.sort(key=lambda item: (-float(item["raw_score"]), str(item["path"])))
    raw_candidates = raw_candidates[:10]
    max_score = max((float(item["raw_score"]) for item in raw_candidates), default=1.0)

    candidate_files = [
        {
            "path": item["path"],
            "score": round(float(item["raw_score"]) / max_score, 2) if max_score else 0.0,
            "language": item["language"],
            "role": item["role"],
            "reasons": item["reasons"],
        }
        for item in raw_candidates
    ]
    candidate_paths = {item["path"] for item in candidate_files}

    related_symbols = _related_symbols(symbols, tokens, candidate_paths)
    recent_commits = _recent_commits(query_commits, candidate_paths)
    diagnostics = _context_diagnostics(query, candidate_files)

    return {
        "query": query,
        "candidate_files": candidate_files,
        "suggested_first_reads": [item["path"] for item in candidate_files[:5]],
        "related_symbols": related_symbols[:10],
        "recent_commits": recent_commits[:5],
        "confidence": diagnostics["confidence"],
        "next_agent_actions": diagnostics["next_agent_actions"],
    }


def _tokens(query: str) -> list[str]:
    return tokenize_query(query)


def _token_weights(
    tokens: list[str],
    files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    commit_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    if not tokens:
        return {}
    commit_messages = {}
    for row in commit_rows:
        commit_messages[int(row["id"])] = str(row.get("message") or "").lower()
    documents = [str(item.get("path") or "").lower() for item in files]
    documents.extend(str(item.get("name") or "").lower() for item in symbols)
    documents.extend(commit_messages.values())
    total = max(len(documents), 1)
    weights = {}
    for token in tokens:
        frequency = sum(1 for document in documents if token in document)
        raw = 0.65 + log((total + 1) / (frequency + 1))
        weights[token] = {"all": max(0.35, min(2.4, raw))}
    return weights


def _load_term_weights(conn: Any, tokens: list[str]) -> dict[str, dict[str, float]]:
    if not tokens:
        return {}
    try:
        placeholders = ",".join("?" for _ in tokens)
        rows = conn.execute(
            f"SELECT term, source, weight FROM term_stats WHERE term IN ({placeholders})",
            tokens,
        ).fetchall()
    except Exception:
        return {}
    weights: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        weights[str(row["term"])][str(row["source"])] = float(row["weight"])
    return {token: weights.get(token, {"all": 0.25}) for token in tokens} if weights else {}


def _weight(token_weights: dict[str, Any], token: str, source: str = "all") -> float:
    value = token_weights.get(token, 1.0)
    if isinstance(value, dict):
        return float(value.get(source, value.get("all", 1.0)))
    return float(value)


def _score_files_by_path_role_language(
    files: list[dict[str, Any]],
    tokens: list[str],
    token_weights: dict[str, Any],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    for file_item in files:
        path = str(file_item["path"])
        path_parts = _path_tokens(path)
        filename = Path(path).name
        filename_parts = _path_tokens(filename)
        compact_filename = re.sub(r"[^a-z0-9]+", "", Path(filename).stem.lower())
        language = str(file_item.get("language") or "").lower()
        role = str(file_item.get("role") or "").lower()
        for token in tokens:
            path_weight = _weight(token_weights, token, "path")
            filename_weight = _weight(token_weights, token, "filename")
            exact_path = token in path_parts
            exact_filename = token in filename_parts
            if exact_path:
                file_scores[path] += 7 * path_weight
                _add_reason(reasons[path], f'path matches "{token}"')
                _add_weight_reason(reasons[path], token, path_weight)
            if exact_filename:
                file_scores[path] += 5 * filename_weight
                _add_reason(reasons[path], f'filename matches "{token}"')
                _add_weight_reason(reasons[path], token, filename_weight)
            elif len(token) >= 5 and token in compact_filename:
                file_scores[path] += 4 * filename_weight
                _add_reason(reasons[path], f'filename contains "{token}"')
                _add_weight_reason(reasons[path], token, filename_weight)
            if not exact_path:
                path_soft = _best_soft_match(token, path_parts)
                if path_soft >= 0.78:
                    file_scores[path] += 2.5 * path_weight * path_soft
                    _add_reason(reasons[path], f'path softly matches "{token}"')
            if not exact_filename:
                filename_soft = _best_soft_match(token, filename_parts)
                if filename_soft >= 0.78:
                    file_scores[path] += 2.0 * filename_weight * filename_soft
                    _add_reason(reasons[path], f'filename softly matches "{token}"')
            if token and (token in role or token in language):
                role_weight = _weight(token_weights, token, "role")
                language_weight = _weight(token_weights, token, "language")
                weight = max(role_weight, language_weight)
                file_scores[path] += 1.5 * weight
                _add_reason(reasons[path], f'role/language matches "{token}"')
                _add_weight_reason(reasons[path], token, weight)


def _score_files_by_symbols(
    symbols: list[dict[str, Any]],
    tokens: list[str],
    token_weights: dict[str, Any],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    matched_by_file: dict[str, set[str]] = defaultdict(set)
    has_docs_intent = any(token in DOCS_INTENT_TOKENS for token in tokens)
    for symbol in symbols:
        name = str(symbol["name"])
        name_lower = name.lower()
        path = str(symbol["file"])
        file_role = str(symbol.get("file_role") or "")
        kind = str(symbol.get("kind") or "")
        for token in tokens:
            if token in name_lower and token not in matched_by_file[path]:
                matched_by_file[path].add(token)
                weight = _weight(token_weights, token, "symbol")
                multiplier = 1.0
                if file_role == "documentation" and not has_docs_intent:
                    multiplier = 0.25 if kind in {"heading", "command_example"} else 0.5
                file_scores[path] += 3.5 * weight * multiplier
                _add_reason(reasons[path], f'symbol matches "{token}"')
                _add_weight_reason(reasons[path], token, weight)


def _score_files_by_commits(
    commit_rows: list[dict[str, Any]],
    tokens: list[str],
    token_weights: dict[str, Any],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> list[dict[str, Any]]:
    commits_by_id: dict[int, dict[str, Any]] = {}
    for row in commit_rows:
        commit_id = int(row["id"])
        commit = commits_by_id.setdefault(
            commit_id,
            {
                "id": commit_id,
                "hash": row["hash"],
                "date": row["date"],
                "message": row["message"],
                "files": [],
                "matched": False,
            },
        )
        if row.get("path"):
            commit["files"].append(row["path"])

    query_commits: list[dict[str, Any]] = []
    for commit in commits_by_id.values():
        message = str(commit.get("message") or "").lower()
        matched_tokens = [token for token in tokens if token in message]
        if not matched_tokens:
            continue
        commit["matched"] = True
        query_commits.append(commit)
        scored_paths: set[tuple[str, str]] = set()
        for path in commit["files"]:
            for token in matched_tokens:
                if (path, token) in scored_paths:
                    continue
                scored_paths.add((path, token))
                weight = _weight(token_weights, token, "commit")
                file_scores[path] += 1.2 * weight
                _add_reason(reasons[path], f'commit message matches "{token}"')
                _add_weight_reason(reasons[path], token, weight)
            file_scores[path] += 0.8
            _add_reason(reasons[path], "modified in recent query-related commit")
    query_commits.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return query_commits


def _score_files_by_calls(
    relations: list[dict[str, Any]],
    file_by_id: dict[int, dict[str, Any]],
    tokens: list[str],
    token_weights: dict[str, Any],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    matched_by_file: dict[str, set[str]] = defaultdict(set)
    for relation in relations:
        if relation.get("relation") != "calls" or relation.get("target_type") != "symbol_name":
            continue
        source = file_by_id.get(int(relation["source_id"]))
        if not source:
            continue
        path = str(source["path"])
        target = str(relation["target_id"])
        target_lower = target.lower()
        for token in tokens:
            if token in target_lower and token not in matched_by_file[path]:
                matched_by_file[path].add(token)
                weight = _weight(token_weights, token, "symbol")
                file_scores[path] += 2.2 * weight
                _add_reason(reasons[path], f'calls "{target}"')
                _add_weight_reason(reasons[path], token, weight)


def _score_related_files(
    relations: list[dict[str, Any]],
    file_by_id: dict[int, dict[str, Any]],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    candidate_paths = {path for path, score in file_scores.items() if score > 0}
    if not candidate_paths:
        return
    target_index = _relation_target_index(candidate_paths)
    related_boosts: dict[str, float] = defaultdict(float)
    related_reason_counts: dict[str, int] = defaultdict(int)
    for relation in relations:
        source = file_by_id.get(int(relation["source_id"]))
        if not source:
            continue
        source_path = str(source["path"])
        target = str(relation["target_id"])
        if source_path in candidate_paths:
            linked_path = _resolve_relation_target(target, target_index)
            if linked_path and linked_path != source_path and related_boosts[linked_path] < 1.5:
                boost = min(0.5, 1.5 - related_boosts[linked_path])
                file_scores[linked_path] += boost
                related_boosts[linked_path] += boost
                if related_reason_counts[linked_path] < 5:
                    related_reason_counts[linked_path] += 1
                    _add_reason(reasons[linked_path], f"related to {source_path}")
        else:
            target_candidate = _resolve_relation_target(target, target_index)
            if not target_candidate or related_boosts[source_path] >= 1.5:
                continue
            boost = min(0.5, 1.5 - related_boosts[source_path])
            file_scores[source_path] += boost
            related_boosts[source_path] += boost
            if related_reason_counts[source_path] < 5:
                related_reason_counts[source_path] += 1
                _add_reason(reasons[source_path], f"related to {target_candidate}")


def _score_files_by_feedback(
    root: Path,
    files: list[dict[str, Any]],
    tokens: list[str],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    indexed_paths = {str(item["path"]) for item in files}
    for path, signal in feedback_signals(root, tokens, indexed_paths).items():
        boost = float(signal.get("boost") or 0.0)
        penalty = float(signal.get("penalty") or 0.0)
        if boost > 0:
            file_scores[path] += boost
            ratings = {str(item) for item in signal.get("positive", set())}
            if "crucial" in ratings:
                _prepend_reason(reasons[path], "previously marked crucial for similar query")
            elif "missing" in ratings:
                _prepend_reason(reasons[path], "previously marked missing from similar query")
            else:
                _prepend_reason(reasons[path], "previously marked useful for similar query")
        if penalty < 0 and file_scores[path] > 0:
            file_scores[path] = max(0.0, file_scores[path] + penalty) * 0.35
            _prepend_reason(reasons[path], "previously marked noisy for similar query")


def _adjust_test_file_scores(
    files: list[dict[str, Any]],
    tokens: list[str],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    test_aware = any(token in TEST_AWARE_TOKENS for token in tokens)
    for file_item in files:
        path = str(file_item["path"])
        if file_scores[path] <= 0 or str(file_item.get("role") or "") != "test":
            continue
        if test_aware:
            _prepend_reason(reasons[path], "test-aware query")
            continue
        file_scores[path] *= 0.45
        _prepend_reason(reasons[path], "test file deprioritized for non-test query")


def _adjust_role_type_scores(
    files: list[dict[str, Any]],
    tokens: list[str],
    file_scores: dict[str, float],
    reasons: dict[str, list[str]],
) -> None:
    has_ui_intent = any(token in UI_INTENT_TOKENS for token in tokens)
    has_db_intent = any(token in DB_INTENT_TOKENS for token in tokens)
    has_docs_intent = any(token in DOCS_INTENT_TOKENS for token in tokens)
    has_example_intent = any(token in EXAMPLE_INTENT_TOKENS for token in tokens)
    for file_item in files:
        path = str(file_item["path"])
        if file_scores[path] <= 0:
            continue
        role = str(file_item.get("role") or "")
        extension = Path(path).suffix.lower()
        if (role == "asset" or extension in ASSET_EXTENSIONS) and not has_ui_intent:
            file_scores[path] *= 0.7
            _prepend_reason(reasons[path], "asset file deprioritized for non-UI query")
        if (role == "migration" or extension in MIGRATION_EXTENSIONS) and not has_db_intent:
            file_scores[path] *= 0.75
            _prepend_reason(reasons[path], "migration file deprioritized for non-database query")
        if (role == "documentation" or extension in DOCS_EXTENSIONS) and not has_docs_intent:
            file_scores[path] *= 0.4
            _prepend_reason(reasons[path], "documentation deprioritized for non-docs query")
        if (role == "documentation" or extension in DOCS_EXTENSIONS) and has_docs_intent:
            file_scores[path] = file_scores[path] * 1.35 + 1.0
            _add_reason(reasons[path], "documentation preferred for docs query")
        if _is_example_path(path) and not has_example_intent:
            file_scores[path] *= 0.5
            _prepend_reason(reasons[path], "example/playground deprioritized for non-example query")
        if role == "source" and extension in SOURCE_BACKEND_EXTENSIONS:
            file_scores[path] = file_scores[path] * 1.05 + 0.1
            _add_reason(reasons[path], "source file preferred")


def _is_example_path(path: str) -> bool:
    for part in Path(path).parts:
        lowered = part.lower()
        if lowered in EXAMPLE_PATH_PARTS:
            return True
        if any(marker in lowered for marker in ("playground", "example", "demo")):
            return True
    return False


def _relation_target_index(candidate_paths: set[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in sorted(candidate_paths):
        normalized = path.lstrip("./")
        parts = normalized.split("/")
        for offset in range(len(parts)):
            index.setdefault("/".join(parts[offset:]), path)
        if parts:
            index.setdefault(parts[-1], path)
    return index


def _resolve_relation_target(target: str, target_index: dict[str, str]) -> str | None:
    normalized = target.lstrip("./")
    return target_index.get(normalized) or target_index.get(_basename(normalized))


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _path_tokens(value: str) -> list[str]:
    parts = []
    for token in re.split(r"[^a-z0-9]+", value.lower()):
        if len(token) >= 3:
            parts.extend(_split_camel_like(token))
    return list(dict.fromkeys(parts))


def _split_camel_like(token: str) -> list[str]:
    pieces = re.sub(r"([a-z])([A-Z])", r"\1 \2", token).lower().split()
    return pieces or [token]


def _best_soft_match(query_token: str, candidates: list[str]) -> float:
    if len(query_token) < 6 or is_query_noise_token(query_token):
        return 0.0
    best = 0.0
    for candidate in candidates:
        if len(candidate) < 5 or is_query_noise_token(candidate):
            continue
        shorter, longer = sorted((query_token, candidate), key=len)
        coverage = len(shorter) / max(len(longer), 1)
        if len(shorter) >= 6 and coverage >= 0.5 and longer.startswith(shorter):
            best = max(best, 0.9)
            continue
        if len(shorter) >= 6 and coverage >= 0.65 and shorter in longer:
            best = max(best, 0.84)
            continue
        ratio = SequenceMatcher(None, query_token, candidate).ratio()
        if ratio >= 0.82:
            best = max(best, ratio)
    return best


def _related_symbols(symbols: list[dict[str, Any]], tokens: list[str], candidate_paths: set[str]) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for symbol in symbols:
        name = str(symbol["name"])
        name_lower = name.lower()
        path = str(symbol["file"])
        score = 0
        if path in candidate_paths:
            score += 1
        if any(token in name_lower for token in tokens):
            score += 3
        if score:
            ranked.append(
                (
                    score,
                    {
                        "name": name,
                        "kind": symbol["kind"],
                        "file": path,
                        "line": symbol["line"] or 0,
                    },
                )
            )
    ranked.sort(key=lambda item: (-item[0], str(item[1]["file"]), int(item[1]["line"])))
    return [item for _, item in ranked]


def _recent_commits(query_commits: list[dict[str, Any]], candidate_paths: set[str]) -> list[dict[str, Any]]:
    result = []
    for commit in query_commits:
        files = list(dict.fromkeys(path for path in commit.get("files", []) if path))
        if not files or candidate_paths.intersection(files):
            total_files = len(files)
            result.append(
                {
                    "hash": commit["hash"],
                    "date": commit["date"],
                    "message": commit["message"],
                    "files": files[:MAX_COMMIT_FILES],
                    "total_files": total_files,
                    "files_truncated": total_files > MAX_COMMIT_FILES,
                }
            )
    return result


def _context_diagnostics(query: str, candidate_files: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    tokens = _tokens(query)
    if not candidate_files:
        reasons.append("no candidate files were found")
        return {
            "confidence": {"level": "low", "reasons": reasons},
            "next_agent_actions": _recovery_actions(query, no_candidates=True),
        }

    broad_candidates = sum(1 for item in candidate_files if float(item.get("score") or 0.0) >= 0.5)
    top_reasons = [str(reason) for reason in candidate_files[0].get("reasons", [])]
    strong_reason = any(_is_strong_reason(reason) for reason in top_reasons)
    weak_soft_reasons = sum(
        1
        for item in candidate_files[:8]
        for reason in item.get("reasons", [])
        if "softly matches" in str(reason)
    )
    if broad_candidates >= 6:
        reasons.append("many candidates have similar scores")
    if not strong_reason:
        reasons.append("top candidate is not supported by strong symbol, call, feedback or exact filename signals")
    if weak_soft_reasons >= 5:
        reasons.append("ranking is driven by broad soft path matches")
    symptom_test_candidate = _symptom_test_candidate(tokens, candidate_files)
    if _is_symptom_query(tokens) and symptom_test_candidate and _has_generic_symptom_candidates(candidate_files):
        reasons.append("symptom or failing-test query may point at high-level files before the underlying cause")

    if len(reasons) >= 2 or (reasons and not strong_reason):
        level = "low"
    elif reasons:
        level = "medium"
    else:
        level = "high"
    if symptom_test_candidate and any("underlying cause" in reason for reason in reasons):
        level = "medium" if level == "high" else level
    return {
        "confidence": {"level": level, "reasons": reasons},
        "next_agent_actions": (
            _recovery_actions(query, no_candidates=False, candidate_files=candidate_files)
            if level in {"low", "medium"}
            else _verification_actions(query, candidate_files)
        ),
    }


def _is_strong_reason(reason: str) -> bool:
    return any(
        marker in reason
        for marker in (
            "previously marked",
            "symbol matches",
            "calls ",
            "filename matches",
            "filename contains",
            "path matches",
            "modified in recent query-related commit",
        )
    )


def _symptom_test_candidate(tokens: list[str], candidate_files: list[dict[str, Any]]) -> str:
    if not _is_symptom_query(tokens):
        return ""
    for item in candidate_files[:8]:
        path = str(item.get("path") or "")
        role = str(item.get("role") or "")
        path_parts = set(_path_tokens(path))
        if role == "test" or "test" in path_parts or "tests" in path_parts:
            return path
    return ""


def _is_symptom_query(tokens: list[str]) -> bool:
    token_set = set(tokens)
    return bool(token_set.intersection(SYMPTOM_QUERY_TOKENS) or token_set.intersection(TEST_AWARE_TOKENS))


def _has_generic_symptom_candidates(candidate_files: list[dict[str, Any]]) -> bool:
    for item in candidate_files[:5]:
        path_tokens = set(_path_tokens(str(item.get("path") or "")))
        if path_tokens.intersection(GENERIC_SYMPTOM_PATH_TOKENS):
            return True
    return False


def _recovery_actions(query: str, no_candidates: bool, candidate_files: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    reason = "context pack is empty" if no_candidates else "context pack confidence is low or noisy"
    quoted = _shell_double_quote(query)
    actions: list[dict[str, str]] = []
    test_path = _symptom_test_candidate(_tokens(query), candidate_files or [])
    if test_path:
        actions.append(
            {
                "action": "inspect_failing_test_neighborhood",
                "command": f"init-agent related {test_path}",
                "reason": "for symptom-heavy or failing-test queries, inspect the test neighborhood to find lower-level implementation files before broad reading",
            }
        )
    actions.extend(
        [
            {
                "action": "check_index",
                "command": "init-agent doctor",
                "reason": "verify whether the local index is missing, stale or unhealthy",
            },
            {
                "action": "refresh_index",
                "command": "init-agent map",
                "reason": "rebuild the map if doctor reports missing, empty or stale index data",
            },
            {
                "action": "narrow_query",
                "command": f"init-agent run {quoted} --markdown",
                "reason": f"{reason}; retry with concrete module, symbol, route, table, error or workflow terms before broad reading",
            },
            {
                "action": "record_feedback_after_verification",
                "command": f"init-agent feedback add {quoted} <path> --rating noisy --source agent --reason \"verified irrelevant suggestion\"",
                "reason": "teach future runs when a suggested file was verified as noisy",
            },
        ]
    )
    return actions


def _verification_actions(query: str, candidate_files: list[dict[str, Any]]) -> list[dict[str, str]]:
    first_path = str(candidate_files[0].get("path") or "")
    if not first_path:
        return []
    quoted = _shell_double_quote(query)
    return [
        {
            "action": "inspect_top_candidate",
            "command": f"init-agent related {first_path}",
            "reason": "verify the top candidate before editing or trusting the ranking",
        },
        {
            "action": "record_feedback_after_verification",
            "command": f"init-agent feedback add {quoted} {first_path} --rating useful --source agent --reason \"verified relevant\"",
            "reason": "record useful feedback only after verifying the file",
        },
    ]


def _shell_double_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _add_reason(items: list[str], reason: str) -> None:
    if reason not in items:
        items.append(reason)


def _prepend_reason(items: list[str], reason: str) -> None:
    if reason in items:
        items.remove(reason)
    items.insert(0, reason)


def _add_weight_reason(items: list[str], token: str, weight: float) -> None:
    if weight <= 1.2:
        _add_reason(items, f'common token "{token}" downweighted')
    elif weight >= 1.4:
        _add_reason(items, f'specific token "{token}" boosted')
