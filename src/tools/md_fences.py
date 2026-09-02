"""Structural fences for the .md direct-translation path.

The model is never shown Markdown. This module cuts a document into
alternating pieces — literal skeleton (fences, pipes, bullets, code, URLs)
and translatable slots (prose) — and puts it back together afterwards, so
structure is preserved by the program rather than by asking an LLM nicely.
Every slot the owner asked for is covered: prose, headings, list items,
table cells, comments inside code blocks, mermaid labels, and the annotation
column of a plain-text directory tree.

Slot modes decide who handles a slot:
- "translate" — English prose, goes to the LLM;
- "opencc" — the text already contains Han characters, so it is converted
  Traditional→Simplified instead of being "translated" into Chinese twice.

Inline spans that must survive byte-for-byte (inline code, URLs, images,
math, HTML tags) are swapped for ⟦n⟧ placeholders before a slot leaves the
program and restored after, so a model that drops formatting cannot damage
them.
"""

import re

PLACEHOLDER_RE = re.compile(r"⟦(\d+)⟧")

_HAN_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")

_FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w+-]*)")
_HEADING_RE = re.compile(r"^(#{1,6}\s+)(.+)$")
_LIST_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.+)$")
_QUOTE_RE = re.compile(r"^(\s*>\s?)(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|?\s*$")
# "path/to/thing        annotation" — two or more spaces separate a tree
# entry from its description; one space does not (that would eat filenames).
_TREE_RE = re.compile(r"^(\S.*?|\s*[^\s].*?)(\s{2,})(\S.*)$")

# Spans that must reach the output unchanged.
_INLINE_RE = re.compile(
    r"`[^`\n]+`"  # inline code
    r"|!\[[^\]\n]*\]\([^)\n]*\)"  # image (alt text included: it is a caption)
    r"|(?<=\])\([^)\n]*\)"  # a link's target — its text stays translatable
    r"|<[^>\n]+>"  # HTML tag / autolink
    r"|\$\$?[^$\n]+\$\$?"  # math
    r"|https?://\S+"  # bare URL
)

# Comment syntax per fenced-code language. Everything after the marker is
# prose the owner wants translated; the code before it is untouchable.
_LINE_COMMENT = {
    "python": "#", "py": "#", "bash": "#", "sh": "#", "shell": "#", "zsh": "#",
    "console": "#", "yaml": "#", "yml": "#", "toml": "#", "ini": "#", "conf": "#",
    "ruby": "#", "rb": "#", "r": "#", "makefile": "#", "dockerfile": "#",
    "js": "//", "javascript": "//", "jsx": "//", "ts": "//", "typescript": "//",
    "tsx": "//", "java": "//", "c": "//", "cpp": "//", "cs": "//", "go": "//",
    "rust": "//", "rs": "//", "swift": "//", "kotlin": "//", "php": "//",
    "sql": "--", "lua": "--", "haskell": "--",
}

# Fences whose content is a diagram or a plain-text figure rather than code.
_MERMAID = {"mermaid"}
_PLAIN = {"", "text", "txt", "plain", "tree", "console-output"}

# Labels inside a mermaid line: quoted strings, node text, edge labels.
_MERMAID_LABEL_RE = re.compile(
    r'"([^"\n]+)"|\[([^\]\n]+)\]|\{([^}\n]+)\}|\(([^)\n]+)\)|\|([^|\n]+)\|'
)


def protect_inline(text: str) -> tuple[str, list[str]]:
    """Replace inline spans with ⟦n⟧ placeholders. Returns the masked text
    and the spans, positionally indexed."""
    spans: list[str] = []

    def _swap(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"⟦{len(spans) - 1}⟧"

    return _INLINE_RE.sub(_swap, text), spans


def restore_inline(text: str, spans: list[str]) -> str:
    """Put the protected spans back. A placeholder the model dropped or
    invented is handled defensively: unknown indexes become empty strings,
    and spans never referenced are appended so their content is not lost."""
    seen: set[int] = set()

    def _swap(match: re.Match) -> str:
        index = int(match.group(1))
        seen.add(index)
        return spans[index] if index < len(spans) else ""

    out = PLACEHOLDER_RE.sub(_swap, text)
    missing = [s for i, s in enumerate(spans) if i not in seen]
    return out + ("".join(f" {s}" for s in missing) if missing else "")


def slot_mode(text: str) -> str | None:
    """How a candidate string should be handled — None means "leave it alone"
    (no letters at all: separators, numbers, punctuation, bare paths)."""
    if _HAN_RE.search(text):
        return "opencc"
    if _LATIN_RE.search(text):
        return "translate"
    return None


class _Builder:
    def __init__(self) -> None:
        self.pieces: list[dict] = []

    def literal(self, text: str) -> None:
        if not text:
            return
        if self.pieces and self.pieces[-1]["kind"] == "literal":
            self.pieces[-1]["text"] += text
        else:
            self.pieces.append({"kind": "literal", "text": text})

    def slot(self, text: str) -> None:
        """Add a translatable slot — or a literal when the text carries no
        prose (so the model is never billed for "|---|" or "v3.2")."""
        mode = slot_mode(text)
        if mode is None:
            self.literal(text)
            return
        masked, spans = protect_inline(text)
        if slot_mode(masked) is None:  # e.g. a line that was only a URL
            self.literal(text)
            return
        self.pieces.append(
            {"kind": "slot", "id": self._next_id(), "text": masked, "spans": spans, "mode": mode}
        )

    def _next_id(self) -> int:
        return sum(1 for p in self.pieces if p["kind"] == "slot")


def _split_comment(line: str, marker: str) -> tuple[str, str] | None:
    """Split a code line into (code + marker, comment). Quote-aware, so a
    marker inside a string literal ("#!/bin/sh", "http://x") is not one."""
    quote = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif line.startswith(marker, i):
            # A marker glued to a word (URL fragment, shebang) is not a comment.
            if i and not line[i - 1].isspace():
                return None
            return line[: i + len(marker)], line[i + len(marker) :]
        i += 1
    return None


def _emit_code_line(builder: _Builder, line: str, lang: str) -> None:
    marker = _LINE_COMMENT.get(lang)
    split = _split_comment(line, marker) if marker else None
    if split is None:
        builder.literal(line)
        return
    head, comment = split
    # Indentation after the marker belongs to the skeleton, not the prose.
    indent = comment[: len(comment) - len(comment.lstrip())]
    builder.literal(head + indent)
    builder.slot(comment[len(indent) :])


def _emit_mermaid_line(builder: _Builder, line: str) -> None:
    last = 0
    for match in _MERMAID_LABEL_RE.finditer(line):
        inner = next(g for g in match.groups() if g is not None)
        start = match.start() + (match.group(0).index(inner))
        builder.literal(line[last:start])
        builder.slot(inner)
        last = start + len(inner)
    builder.literal(line[last:])


def _emit_plain_line(builder: _Builder, line: str) -> None:
    """Plain-text fence: a directory tree or an ASCII figure. Only the
    annotation column (separated by 2+ spaces) is prose."""
    match = _TREE_RE.match(line)
    if not match:
        builder.literal(line)
        return
    builder.literal(match.group(1) + match.group(2))
    builder.slot(match.group(3))


def _emit_table_row(builder: _Builder, line: str) -> None:
    cells = line.split("|")
    for index, cell in enumerate(cells):
        if index:
            builder.literal("|")
        stripped = cell.strip()
        if not stripped:
            builder.literal(cell)
            continue
        lead = cell[: len(cell) - len(cell.lstrip())]
        trail = cell[len(cell.rstrip()) :]
        builder.literal(lead)
        builder.slot(stripped)
        builder.literal(trail)


def _is_continuation(line: str) -> bool:
    """Is this line the wrapped remainder of the list item above it?"""
    if not line.strip():
        return False
    return not (
        _FENCE_RE.match(line)
        or _HEADING_RE.match(line)
        or _LIST_RE.match(line)
        or _QUOTE_RE.match(line)
        or line.lstrip().startswith("|")
    )


def segment(markdown: str) -> list[dict]:
    """Cut a Markdown document into literal/slot pieces (see module docs)."""
    builder = _Builder()
    lines = markdown.split("\n")
    i = 0
    fence: str | None = None
    lang = ""
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            builder.slot("\n".join(paragraph))
            paragraph.clear()

    # YAML front matter is configuration, not prose — never touched.
    if lines and lines[0].strip() == "---":
        for end in range(1, len(lines)):
            if lines[end].strip() in ("---", "..."):
                builder.literal("\n".join(lines[: end + 1]))
                i = end + 1
                break

    while i < len(lines):
        line = lines[i]
        fence_match = _FENCE_RE.match(line)

        if fence is not None:
            builder.literal("\n" if i else "")
            if line.strip().startswith(fence):
                builder.literal(line)
                fence = None
            elif lang in _MERMAID:
                _emit_mermaid_line(builder, line)
            elif lang in _PLAIN:
                _emit_plain_line(builder, line)
            else:
                _emit_code_line(builder, line, lang)
            i += 1
            continue

        if fence_match:
            flush_paragraph()
            builder.literal(("\n" if i else "") + line)
            fence = fence_match.group(2)
            lang = fence_match.group(3).lower()
            i += 1
            continue

        heading = _HEADING_RE.match(line)
        listing = _LIST_RE.match(line)
        quote = _QUOTE_RE.match(line)
        is_table = line.lstrip().startswith("|")

        if not line.strip():
            flush_paragraph()
            builder.literal(("\n" if i else "") + line)
        elif listing:
            # A wrapped list item is ONE unit of prose: its continuation
            # lines are swallowed here, or the model would translate half a
            # sentence at a time.
            flush_paragraph()
            builder.literal("\n" if i else "")
            builder.literal(listing.group(1))
            item = [listing.group(2)]
            while i + 1 < len(lines) and _is_continuation(lines[i + 1]):
                i += 1
                item.append(lines[i])
            builder.slot("\n".join(item))
        elif heading or quote or is_table:
            flush_paragraph()
            builder.literal("\n" if i else "")
            if is_table:
                if _TABLE_SEP_RE.match(line):
                    builder.literal(line)
                else:
                    _emit_table_row(builder, line)
            else:
                match = heading or quote
                builder.literal(match.group(1))
                builder.slot(match.group(2))
        else:
            if not paragraph:
                builder.literal("\n" if i else "")
            paragraph.append(line)
        i += 1

    flush_paragraph()
    return builder.pieces


def slots(pieces: list[dict]) -> list[dict]:
    return [p for p in pieces if p["kind"] == "slot"]


def rebuild(pieces: list[dict], translations: dict[int, str]) -> str:
    """Reassemble the document, substituting each slot's translation (or its
    source text when a slot has none) and restoring protected spans."""
    out: list[str] = []
    for piece in pieces:
        if piece["kind"] == "literal":
            out.append(piece["text"])
        else:
            text = translations.get(piece["id"], piece["text"])
            out.append(restore_inline(text, piece.get("spans", [])))
    return "".join(out)
