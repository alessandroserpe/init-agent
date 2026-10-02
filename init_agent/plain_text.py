"""Encode data fields before composing renderer-owned lines."""
from .utils import terminal_safe


def plain_fields(value):
    if isinstance(value, str):
        return terminal_safe(value.replace('\r', r'\r').replace('\n', r'\n').replace('\t', r'\t').replace('\u2028', r'\u2028').replace('\u2029', r'\u2029'))
    if isinstance(value, dict):
        return {plain_fields(key): plain_fields(item) for key, item in value.items()}
    if isinstance(value, list):
        return [plain_fields(item) for item in value]
    if isinstance(value, tuple):
        return tuple(plain_fields(item) for item in value)
    return value
