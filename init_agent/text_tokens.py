"""Shared token filtering helpers."""

from __future__ import annotations

import re


SHORT_TECH_TOKENS = {"ai", "api", "css", "db", "go", "js", "php", "py", "sql", "ts", "ui"}

QUERY_NOISE_TOKENS = {
    "capire",
    "codice",
    "code",
    "file",
    "progetto",
    "project",
    "repo",
    "repository",
    "skill",
    "usando",
}

FUNCTION_WORDS = {
    "a",
    "after",
    "and",
    "are",
    "before",
    "che",
    "come",
    "con",
    "da",
    "del",
    "della",
    "di",
    "does",
    "dopo",
    "dove",
    "for",
    "from",
    "ha",
    "handle",
    "how",
    "il",
    "in",
    "is",
    "la",
    "le",
    "lo",
    "non",
    "not",
    "of",
    "on",
    "per",
    "perche",
    "perché",
    "prima",
    "questa",
    "questo",
    "se",
    "the",
    "to",
    "un",
    "una",
    "when",
    "where",
    "with",
    "why",
}


def is_query_noise_token(token: str) -> bool:
    if token in QUERY_NOISE_TOKENS or token in FUNCTION_WORDS:
        return True
    return len(token) < 3 and token not in SHORT_TECH_TOKENS


def tokenize_query(query: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_]+", query.lower()):
        if token in seen or is_query_noise_token(token):
            continue
        seen.add(token)
        result.append(token)
    return result
