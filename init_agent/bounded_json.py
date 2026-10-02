"""Byte and structure limits before JSON decoding; bounded object measurement."""
import json

MAX_DEPTH = 32
MAX_TOKENS = 16384


def read_bounded(stream, limit):
    chunks = []
    remaining = limit + 1
    while remaining:
        chunk = stream.read(min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = (b'' if not chunks or isinstance(chunks[0], bytes) else '').join(chunks)
    if len(value) > limit:
        raise ValueError('JSON byte limit exceeded')
    if isinstance(value, str):
        value = value.encode('utf-8')
    if len(value) > limit:
        raise ValueError('JSON byte limit exceeded')
    return value


def decode_bounded(body, limit):
    if len(body) > limit:
        raise ValueError('JSON byte limit exceeded')
    depth = tokens = 0
    quoted = escaped = False
    for char in body:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
            tokens += 1
        elif char in (123, 91):
            depth += 1
            tokens += 1
        elif char in (125, 93):
            depth -= 1
        elif char in (44, 58):
            tokens += 1
        if depth > MAX_DEPTH or tokens > MAX_TOKENS:
            raise ValueError('JSON structure limit exceeded')
    try:
        return json.loads(body.decode('utf-8'))
    except RecursionError as exc:
        raise ValueError('JSON nesting limit exceeded') from exc


def measure_bounded(value, limit=1048576):
    """Estimate JSON character size without serializing or copying containers.

    Enforce traversal/depth/character limits as well, including direct API calls.
    Escaping overhead is not included; the result is explicitly an estimate.
    """
    stack = [iter((value,))]
    size = nodes = 0
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        if nodes > MAX_TOKENS or len(stack) > MAX_DEPTH:
            raise ValueError('JSON object structure limit exceeded')
        if isinstance(item, str):
            size += len(item) + 3
        elif isinstance(item, dict):
            size += 2
            stack.append((part for pair in item.items() for part in pair))
        elif isinstance(item, (list, tuple)):
            size += 2
            stack.append(iter(item))
        elif item is None or isinstance(item, (bool, float)):
            size += 24
        elif isinstance(item, int):
            size += max(1, item.bit_length()) + 1
        else:
            raise ValueError('non-JSON hook value')
        if size > limit:
            raise ValueError('JSON object size limit exceeded')
    return size
