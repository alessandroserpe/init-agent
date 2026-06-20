"""Shared token filtering helpers."""

from __future__ import annotations


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
