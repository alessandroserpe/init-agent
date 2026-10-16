"""Unicode-aware normalization for full-text source and query terms."""
import re
import unicodedata

from .text_tokens import FUNCTION_WORDS, identifier_terms


def search_terms(value):
    """Preserve Unicode words and existing ASCII identifier splitting rules."""
    result = []
    for word in re.findall(r'[^\W_]+', unicodedata.normalize('NFC', value)):
        if word.isascii():
            pieces = identifier_terms(word)
        else:
            starts = [0]
            for i in range(1, len(word)):
                before, current = word[i-1], word[i]
                following = word[i+1] if i+1 < len(word) else ''
                if (before.isdigit() != current.isdigit()
                        or (before.islower() and current.isupper())
                        or (before.isupper() and current.isupper() and following.islower())):
                    starts.append(i)
            starts.append(len(word))
            pieces = [word[a:b].lower() for a,b in zip(starts, starts[1:])]
        result.extend(piece for piece in pieces if piece not in FUNCTION_WORDS)
    return result
