"""Bounded source passages with parser-provided enclosing symbol context."""
from collections import Counter, defaultdict
from .repo_budget import checkpoint


MAX_PASSAGE_CHARS = 8192


class OversizedPassage(ValueError):
    """A single source line cannot fit the bounded passage representation."""


def passages(lines, symbols):
    """Split at known scope starts/ends; never infer missing end positions."""
    n = len(lines)
    events = defaultdict(Counter)
    declarations = defaultdict(list)
    for symbol in symbols:
        checkpoint()
        first, last = symbol['line'], symbol['end_line']
        if not isinstance(first, int) or not 1 <= first <= n:
            continue
        declarations[first].append(symbol['name'])
        if isinstance(last, int) and first <= last <= n:
            events[first][symbol['name']] += 1
            events[last + 1][symbol['name']] -= 1
        else:
            # Only the declaration line has established ownership.
            events[first]
            events[first + 1]
    boundaries = sorted({1, n + 1, *events})
    active = Counter()
    for first, stop in zip(boundaries, boundaries[1:]):
        checkpoint()
        active.update(events[first])
        active = +active
        start = first
        while start < stop:
            end, size = start, 0
            while end < min(start + 24, stop):
                length = len(lines[end - 1])
                if length > MAX_PASSAGE_CHARS:
                    raise OversizedPassage('source line exceeds passage character limit')
                if size + length + (end > start) > MAX_PASSAGE_CHARS:
                    break
                size += length + (end > start)
                end += 1
            names = set(active)
            for line in range(start, end):
                names.update(declarations.get(line, ()))
            yield start, end - 1, '\n'.join(lines[start - 1:end - 1]), sorted(names)
            start = min(start + 20, end)
