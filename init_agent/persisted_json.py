"""Validate untrusted SQLite JSON before decoding or using typed fields."""
import math
from .bounded_json import decode_bounded

MAX_PERSISTED_BYTES = 16384
CORRUPT_METADATA_WARNING = 'Invalid index JSON metadata omitted; results are partial. Rebuild the index.'


class CorruptMetadata(ValueError):
    pass


def decode_persisted_object(value, *, relation=False):
    try:
        if value is None or value == '':
            return {}
        if not isinstance(value, str) or len(value) > MAX_PERSISTED_BYTES:
            raise ValueError('invalid metadata text')
        parsed = decode_bounded(value.encode('utf-8'), MAX_PERSISTED_BYTES,
                                max_depth=2 if relation else 32,
                                max_tokens=512 if relation else 16384)
        if not isinstance(parsed, dict):
            raise ValueError('metadata must be an object')
        if relation:
            validate_relation_object(parsed)
        return parsed
    except (ValueError, TypeError, RecursionError, MemoryError) as exc:
        raise CorruptMetadata(CORRUPT_METADATA_WARNING) from exc


def validate_relation_object(value):
    if not isinstance(value, dict) or len(value) > 64:
        raise ValueError('relation metadata must be a small object')
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 128:
            raise ValueError('invalid relation metadata key')
        if item is not None and type(item) not in (str, int, float, bool):
            raise ValueError('relation metadata must contain only scalar values')
        if isinstance(item, str) and len(item) > 4096:
            raise ValueError('relation metadata string limit exceeded')
        if type(item) is int and not -(2**63) <= item < 2**63:
            raise ValueError('relation metadata integer limit exceeded')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('nonfinite relation metadata number')
    raw_id = value.get('raw_relation_id')
    if raw_id is not None and (type(raw_id) is not int or raw_id < 1):
        raise ValueError('raw_relation_id must be a positive integer')
