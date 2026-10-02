"""Cooperative per-file parser limits and safe failure reporting."""

from __future__ import annotations

import io
import tokenize
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

MAX_PARSE_BYTES = 2_000_000
MAX_PARSE_DEPTH = 64
MAX_PARSE_TOKENS = 100_000
MAX_PARSE_NODES = 50_000
MAX_PARSE_RECORDS = 10_000
MAX_PARSE_SECONDS = 2.0


class ParseFailure(ValueError):
    """A bounded reason that can be reported without source snippets."""


@dataclass
class ParseBudget:
    nodes: int = 0
    records: int = 0
    started: float = field(default_factory=monotonic)

    def check(self, *, node: bool = False, record: bool = False) -> None:
        self.nodes += int(node)
        self.records += int(record)
        if self.nodes > MAX_PARSE_NODES or self.records > MAX_PARSE_RECORDS:
            raise ParseFailure("parser node/record budget exceeded")
        if monotonic() - self.started > MAX_PARSE_SECONDS:
            raise ParseFailure("parser elapsed-time budget exceeded")


CURRENT_PARSE_BUDGET: ContextVar[ParseBudget | None] = ContextVar("parse_budget", default=None)


def parser_checkpoint(*, node: bool = False, record: bool = False) -> None:
    budget = CURRENT_PARSE_BUDGET.get()
    if budget is not None:
        budget.check(node=node, record=record)


def checked_lines(content: str):
    for line in content.splitlines():
        parser_checkpoint()
        yield line


def preflight(content: str, language: str) -> None:
    if len(content) > MAX_PARSE_BYTES or len(content.encode("utf-8", errors="replace")) > MAX_PARSE_BYTES:
        raise ParseFailure("parser input byte limit exceeded")
    if language == "python":
        _python_preflight(content)
    elif language in {"json", "toml", "php", "javascript", "typescript", "go", "rust"}:
        _delimited_preflight(content)


def _python_preflight(content: str) -> None:
    depth = indents = lambdas = 0
    expressions = [0]
    try:
        for count, token in enumerate(tokenize.generate_tokens(io.StringIO(content).readline), 1):
            parser_checkpoint()
            if count > MAX_PARSE_TOKENS:
                raise ParseFailure("parser token budget exceeded")
            if token.type == tokenize.OP:
                if token.string in ("(", "[", "{"):
                    depth += 1
                    expressions.append(0)
                elif token.string in (")", "]", "}"):
                    depth = max(0, depth - 1)
                    if len(expressions) > 1:
                        expressions.pop()
            if token.type == tokenize.INDENT:
                indents += 1
            elif token.type == tokenize.DEDENT:
                indents -= 1
            # Count expression chains separately at each delimiter depth. A
            # comma in an inner call must not reset its outer addition chain.
            if token.type == tokenize.NEWLINE:
                expressions = [0] * len(expressions)
                lambdas = 0
            elif token.type == tokenize.OP and token.string == "," and depth:
                expressions[-1] = 0
            elif token.type not in {tokenize.NL, tokenize.COMMENT}:
                expressions[-1] += 1
            if token.type == tokenize.NAME and token.string == "lambda":
                lambdas += 1
            if max(depth, indents) > MAX_PARSE_DEPTH or expressions[-1] > 512 or lambdas > MAX_PARSE_DEPTH:
                raise ParseFailure("parser nesting/statement limit exceeded")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # The Python extractor retains its bounded regex fallback for invalid syntax.
        return


def _delimited_preflight(content: str) -> None:
    depth = tokens = index = 0
    quote = ""
    while index < len(content):
        if index % 1024 == 0:
            parser_checkpoint()
        char = content[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if content.startswith(quote, index):
                index += len(quote)
                quote = ""
                continue
        elif char in "\"'`":
            tokens += 1
            quote = char * 3 if content.startswith(char * 3, index) else char
            index += len(quote)
            continue
        elif content.startswith("//", index) or char == "#":
            end = content.find("\n", index)
            index = len(content) if end < 0 else end
            continue
        elif content.startswith("/*", index):
            end = content.find("*/", index + 2)
            index = len(content) if end < 0 else end + 2
            continue
        elif char in "([{":
            depth += 1
            tokens += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
            tokens += 1
        elif char.isalnum() or char == "_":
            tokens += 1
            while index + 1 < len(content) and (content[index + 1].isalnum() or content[index + 1] == "_"):
                index += 1
        elif not char.isspace():
            # Include operators and invalid/error characters, not just delimiters.
            tokens += 1
        if depth > MAX_PARSE_DEPTH or tokens > MAX_PARSE_TOKENS:
            raise ParseFailure("parser nesting/token limit exceeded")
        index += 1
