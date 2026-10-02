"""Local term statistics for adaptive context scoring."""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from math import log
from pathlib import Path

from .repo_budget import bounded_write, checkpoint
from .text_tokens import identifier_terms, is_query_noise_token


@bounded_write
def rebuild_term_stats(conn: sqlite3.Connection) -> int:
    """Rebuild metadata-only term statistics from the current index."""

    # Retain counters, never a copy of every document (or a duplicated corpus).
    counters = {}

    def feed(source, terms):
        checkpoint('steps', len(terms))
        for category in (source, 'all'):
            docs, totals, count = counters.setdefault(category, (Counter(), Counter(), 0))
            new_terms = set(terms) - totals.keys()
            checkpoint('records', len(new_terms))
            checkpoint('bytes', sum(len(term.encode('utf-8')) + 128 for term in new_terms))
            totals.update(terms)
            docs.update(set(terms))
            counters[category] = (docs, totals, count + 1)

    for row in conn.execute("SELECT path, language, role FROM files"):
        path = str(row["path"] or "")
        feed("path", _path_terms(path))
        feed("filename", _path_terms(Path(path).name))
        feed("language", _basic_terms(str(row["language"] or "")))
        feed("role", _basic_terms(str(row["role"] or "")))
    for row in conn.execute("SELECT name FROM symbols"):
        feed("symbol", _basic_terms(str(row["name"] or "")))
    for row in conn.execute("SELECT message FROM git_commits"):
        feed("commit", _basic_terms(str(row["message"] or "")))

    def records():
        for source, (docs, totals, count) in counters.items():
            for term in sorted(totals):
                checkpoint()
                weight = max(0.25, min(2.8, 0.45 + log((max(count, 1) + 1) / (docs[term] + 1))))
                yield (term, source, docs[term], totals[term], weight)

    conn.execute("DELETE FROM term_stats")
    conn.executemany(
        "INSERT INTO term_stats(term, source, document_count, total_count, weight) VALUES(?, ?, ?, ?, ?)",
        records(),
    )
    return sum(len(totals) for _, totals, _ in counters.values())


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
    for token in identifier_terms(value):
        terms.extend(_basic_terms(token))
    return terms


def _basic_terms(value: str) -> list[str]:
    terms: list[str] = []
    for token in identifier_terms(value):
        terms.append(token)
    return [term for term in terms if not is_query_noise_token(term)]
