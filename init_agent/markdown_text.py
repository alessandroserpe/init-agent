"""Encode data separately from the Markdown structure that contains it."""
import re
from .utils import terminal_safe


def inline_code(value: object) -> str:
    text = terminal_safe(str(value)).replace('\r', r'\r').replace('\n', r'\n').replace('\t', r'\t')
    fence = '`' * (1 + max((len(run) for run in re.findall(r'`+', text)), default=0))
    if text.startswith(('`', ' ')) or text.endswith(('`', ' ')):
        text = ' ' + text + ' '
    return fence + (text or ' ') + fence
