"""Local term statistics for adaptive context scoring."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from math import log
from pathlib import Path
from typing import Iterable

from .text_tokens import is_query_noise_token


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def rebuild_term_stats(conn: sqlite3.Connection) -> int:
    """Rebuild metadata-only term statistics from the current index."""

    documents: dict[str, list[list[str]]] = defaultdict(list)
    for row in conn.execute("SELECT path, language, role FROM files").fetchall():
        path = str(row["path"] or "")
        documents["path"].append(_path_terms(path))
        documents["filename"].append(_path_terms(Path(path).name))
        documents["language"].append(_basic_terms(str(row["language"] or "")))
        documents["role"].append(_basic_terms(str(row["role"] or "")))

    for row in conn.execute("SELECT name FROM symbols").fetchall():
        documents["symbol"].append(_basic_terms(str(row["name"] or "")))

    for row in conn.execute("SELECT message FROM git_commits").fetchall():
        documents["commit"].append(_basic_terms(str(row["message"] or "")))

    documents["all"] = [item for source in documents.values() for item in source]
    stats = []
    for source, source_documents in documents.items():
        stats.extend(_source_stats(source, source_documents))

    conn.execute("DELETE FROM term_stats")
    conn.executemany(
        """
        INSERT INTO term_stats(term, source, document_count, total_count, weight)
        VALUES(?, ?, ?, ?, ?)
        """,
        stats,
    )
    return len(stats)


def _source_stats(source: str, documents: list[list[str]]) -> list[tuple[str, str, int, int, float]]:
    document_counts: Counter[str] = Counter()
    total_counts: Counter[str] = Counter()
    for terms in documents:
        total_counts.update(terms)
        document_counts.update(set(terms))

    total_documents = max(len(documents), 1)
    result = []
    for term in sorted(total_counts):
        document_count = document_counts[term]
        raw_weight = 0.45 + log((total_documents + 1) / (document_count + 1))
        weight = max(0.25, min(2.8, raw_weight))
        result.append((term, source, document_count, total_counts[term], weight))
    return result


def _path_terms(value: str) -> list[str]:
    terms: list[str] = []
    for token in re.split(r"[^A-Za-z0-9_]+", value):
        terms.extend(_basic_terms(token))
    return terms


def _basic_terms(value: str) -> list[str]:
    terms: list[str] = []
    for token in TOKEN_RE.findall(value):
        terms.extend(_split_identifier(token))
    return [term for term in terms if not is_query_noise_token(term)]


def _split_identifier(token: str) -> Iterable[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token.replace("_", " "))
    for part in spaced.lower().split():
        if part:
            yield part
