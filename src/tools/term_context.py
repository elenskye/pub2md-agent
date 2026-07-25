"""Extract a real example sentence for a glossary term from article text.

Used when recording term_occurrences: the wordbook export (Phase 4) shows
each term inside a sentence the user actually read, so the example must be
lifted verbatim from the source paragraphs, never generated.
"""

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")
_MAX_LEN = 300


def extract_example(term: str, paragraphs: list[str], max_len: int = _MAX_LEN) -> str:
    """First sentence containing the term (case-insensitive), truncated to
    max_len. Falls back to the start of the first matching paragraph when
    sentence splitting fails to isolate the term; empty string if the term
    does not occur at all."""
    needle = term.lower()
    for para in paragraphs:
        if needle not in para.lower():
            continue
        for sentence in _SENTENCE_SPLIT.split(para):
            if needle in sentence.lower():
                return sentence.strip()[:max_len]
        return para.strip()[:max_len]
    return ""
