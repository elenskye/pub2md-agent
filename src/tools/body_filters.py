"""Deterministic non-body filters (v3 Phase 3 — output purity rule).

The output must contain only the article title, body text and display
formulas. This module holds the zero-cost, high-precision half of that
guarantee: regex kill-lists, caption openers and the references cut. The
fuzzy remainder (author blocks, journal furniture without obvious
markers) is handled by the LLM body_gatekeeper node, which calls into
this module first so junk never reaches the paid classifier.

Precision beats recall here: a pattern only belongs in the kill-list when
a body paragraph could not plausibly match it.
"""

import re

_KILL_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # email addresses
    re.compile(r"\bdoi\b|doi\.org|\b10\.\d{4,}/", re.IGNORECASE),
    # license/copyright furniture — phrased forms only, so body prose that
    # merely discusses copyright is not caught
    re.compile(
        r"©|all rights reserved|this article is distributed under|"
        r"creative commons attribution|\bcc by(-nc)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"corresponding author|通讯作者", re.IGNORECASE),
    re.compile(r"\bissn\b", re.IGNORECASE),
    re.compile(r"downloaded from", re.IGNORECASE),
]

_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|table|图|表)\s*\d+\s*[.:：]", re.IGNORECASE)

_REFERENCE_HEADINGS = {"references", "bibliography", "reference list", "参考文献"}


def is_killed(text: str) -> bool:
    """True when the paragraph matches a high-precision non-body marker."""
    return any(p.search(text) for p in _KILL_PATTERNS)


def is_caption(text: str) -> bool:
    return bool(_CAPTION_RE.match(text))


def is_reference_heading(text: str) -> bool:
    return text.strip().rstrip(".:：").lower() in _REFERENCE_HEADINGS


def cut_references(paragraphs: list[str], headings: list[bool]) -> tuple[list[str], list[bool], int]:
    """Drop everything from a References/Bibliography heading onward (the
    largest single junk block in academic papers). Returns the truncated
    lists and the number of paragraphs removed."""
    for i, text in enumerate(paragraphs):
        if is_reference_heading(text):
            return paragraphs[:i], headings[:i], len(paragraphs) - i
    return paragraphs, headings, 0


def is_formula(text: str) -> bool:
    return text.lstrip().startswith("$$")


def deterministic_filter(
    paragraphs: list[str], headings: list[bool]
) -> tuple[list[str], list[bool], dict[str, int]]:
    """Apply the references cut plus the kill/caption predicates. Headings
    and display formulas are never touched. Returns kept paragraphs,
    kept heading flags, and removal counts by reason."""
    paragraphs, headings, n_refs = cut_references(paragraphs, headings)
    removed = {"reference": n_refs, "killed": 0, "caption": 0}
    kept_p: list[str] = []
    kept_h: list[bool] = []
    for text, heading in zip(paragraphs, headings):
        if not heading and not is_formula(text):
            if is_killed(text):
                removed["killed"] += 1
                continue
            if is_caption(text):
                removed["caption"] += 1
                continue
        kept_p.append(text)
        kept_h.append(heading)
    return kept_p, kept_h, removed
