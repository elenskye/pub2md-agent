"""Column-aware PDF text extraction and paragraph reflow.

Pure layout logic only (no LLM calls) so it stays unit-testable:
- extract_lines: line-level text + coordinates + font size via PyMuPDF
- noise predicates: page numbers, header furniture, embedded CJK translation
- reflow: cluster lines into columns, merge lines into paragraphs by
  vertical gap and font-size changes, then stitch paragraphs that continue
  across column/page boundaries
"""

import re
import statistics

import pymupdf

from src.agent.state import Line, PageGeometry, Paragraph


class PDFExtractionError(RuntimeError):
    """Raised when the PDF has no usable text layer; the run must abort."""


# Below this many characters across the whole document we assume a
# scanned/image PDF rather than a digital one (OCR is out of scope).
MIN_TEXT_CHARS = 200

# A vertical gap larger than this multiple of the column's typical line
# spacing starts a new paragraph.
PARA_GAP_RATIO = 1.5

# Lines whose x0 differ by more than this are considered different columns.
COLUMN_GAP = 100.0

_TERMINAL_PUNCT = tuple('.!?"”’…:;)') + tuple("。！？」』）")
_DATE_RE = re.compile(r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}$")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿　-〿！-～]")
_HAN_RE = re.compile(r"[一-鿿㐀-䶿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def extract_lines(pdf_path: str) -> tuple[list[Line], list[PageGeometry]]:
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # missing file, corrupt PDF, password, ...
        raise PDFExtractionError(f"Cannot open PDF: {exc}") from exc

    lines: list[Line] = []
    pages: list[PageGeometry] = []
    for pno, page in enumerate(doc):
        pages.append(PageGeometry(width=page.rect.width, height=page.rect.height))
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:  # skip images
                continue
            for ln in block["lines"]:
                # Collapse all whitespace incl. NBSP — trailing invisible
                # space would defeat end-of-sentence checks downstream.
                text = " ".join("".join(span["text"] for span in ln["spans"]).split())
                if not text:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                lines.append(
                    Line(
                        page=pno,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        text=text,
                        font_size=max(span["size"] for span in ln["spans"]),
                    )
                )
    doc.close()

    if sum(len(ln["text"]) for ln in lines) < MIN_TEXT_CHARS:
        raise PDFExtractionError(
            "No usable text layer found (scanned/image PDF?). "
            "OCR is out of scope; aborting instead of degrading."
        )
    return lines, pages


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(_CJK_RE.findall(text)) / len(text)


def is_chinese_line(text: str) -> bool:
    """English source lines never contain Han ideographs, so any Han char
    marks a line of the embedded Chinese translation — even when Latin brand
    names ("Bending Spoons", "Evernote") dilute the CJK character ratio."""
    return bool(_HAN_RE.search(text)) or cjk_ratio(text) > 0.5


def latin_han_counts(text: str) -> tuple[int, int]:
    return len(_LATIN_RE.findall(text)), len(_HAN_RE.findall(text))


def drop_embedded_translation(lines: list[Line]) -> list[Line]:
    """In a majority-English document, Han lines are an embedded translation,
    which per spec 3.1 is always discarded (we re-translate from the English
    source). A majority-Chinese document keeps everything — there Chinese IS
    the source, routed per-article to the OpenCC path instead."""
    latin, han = latin_han_counts(" ".join(ln["text"] for ln in lines))
    if latin > han:
        return [ln for ln in lines if not is_chinese_line(ln["text"])]
    return lines


def is_page_number(line: Line, page: PageGeometry) -> bool:
    return line["text"].isdigit() and len(line["text"]) <= 4 and line["y0"] > 0.85 * page["height"]


def is_header_furniture(line: Line, page: PageGeometry) -> bool:
    """Mastheads like an issue date sitting in the top strip of a page."""
    return bool(_DATE_RE.match(line["text"])) and line["y1"] < 0.15 * page["height"]


def strip_noise(lines: list[Line], pages: list[PageGeometry]) -> list[Line]:
    """Drop page numbers, header furniture, running headers/footers, and (in
    Chinese documents) short Latin-only UI junk left by note-app exports."""
    # A short line repeating verbatim across 2+ pages is a running header or
    # footer (often the article title itself). Keep only its largest-font
    # occurrence — that one is the real title — and drop the copies.
    occurrences: dict[str, list[Line]] = {}
    for ln in lines:
        if len(ln["text"]) <= 60:
            occurrences.setdefault(ln["text"], []).append(ln)
    running_copies: set[int] = set()
    for occs in occurrences.values():
        if len({o["page"] for o in occs}) >= 2:
            best = max(occs, key=lambda o: (o["font_size"], -o["page"], -o["y0"]))
            running_copies.update(id(o) for o in occs if o is not best)

    latin, han = latin_han_counts(" ".join(ln["text"] for ln in lines))
    han_majority = han > latin

    # Lines far below body font size are print artifacts: URL footers,
    # timestamps, footnote markers. Body size is length-weighted so
    # headings/furniture don't skew it.
    sizes = sorted(
        (ln["font_size"] for ln in lines for _ in range(len(ln["text"])))
    )
    body_size = sizes[len(sizes) // 2] if sizes else 0.0

    # Note-app exports (the owner's reading workflow) burn UI chrome into the
    # PDF: property labels plus their values on the same visual row.
    ui_labels = {"Favorite", "Status", "Notebooks", "Edited", "Archive", "Pin"}
    label_rows = {
        (ln["page"], int(ln["y0"] // 4)) for ln in lines if ln["text"] in ui_labels
    }

    kept = []
    for ln in lines:
        page = pages[ln["page"]]
        if is_page_number(ln, page) or is_header_furniture(ln, page):
            continue
        if id(ln) in running_copies:
            continue
        if ln["text"] in ui_labels or (ln["page"], int(ln["y0"] // 4)) in label_rows:
            continue
        if ln["font_size"] < 0.75 * body_size:
            continue
        # In a Chinese document, a standalone short Latin-only line is UI
        # furniture ("Favorite", "Archive", timestamps), not body text.
        if han_majority and len(ln["text"]) < 30 and not _HAN_RE.search(ln["text"]):
            continue
        kept.append(ln)
    return kept


def _cluster_columns(page_lines: list[Line]) -> list[list[Line]]:
    """Group a page's lines into columns by x0 proximity, left to right."""
    ordered = sorted(page_lines, key=lambda ln: ln["x0"])
    columns: list[list[Line]] = []
    for ln in ordered:
        if columns and ln["x0"] - max(l["x0"] for l in columns[-1]) <= COLUMN_GAP:
            columns[-1].append(ln)
        else:
            columns.append([ln])
    for col in columns:
        col.sort(key=lambda ln: (ln["y0"], ln["x0"]))
    return columns


def _join(prev: str, nxt: str) -> str:
    if prev.endswith("-"):
        return prev[:-1] + nxt
    # CJK text has no inter-word spaces; inserting one corrupts the text.
    if _CJK_RE.match(prev[-1]) or _CJK_RE.match(nxt[0]):
        return prev + nxt
    return prev + " " + nxt


def _gap_thresholds(col: list[Line]) -> tuple[dict[int, float], float]:
    """Typical line spacing per font size. A 30pt title is spaced ~36pt while
    12pt body sits at ~14pt; one column-wide median would misjudge one of
    them, so gaps are grouped by the font size of the line pair."""
    by_size: dict[int, list[float]] = {}
    all_gaps: list[float] = []
    for a, b in zip(col, col[1:]):
        gap = b["y0"] - a["y0"]
        if gap <= 0:
            continue
        all_gaps.append(gap)
        if abs(a["font_size"] - b["font_size"]) <= 1.0:
            by_size.setdefault(round(a["font_size"]), []).append(gap)
    default = statistics.median(all_gaps) if all_gaps else col[0]["font_size"] * 1.4
    return {size: statistics.median(g) for size, g in by_size.items()}, default


def _short_line_deficit(col: list[Line]) -> tuple[float, float]:
    """A line ending well before the column's right edge terminates its
    paragraph — the only paragraph signal in documents with uniform line
    spacing. The cutoff adapts to the column's raggedness: justified text
    has near-zero right-edge deficits, ragged-right text (e.g. news PDFs)
    has routine deficits that must not trigger splits."""
    right_edge = max(ln["x1"] for ln in col)
    deficits = sorted(right_edge - ln["x1"] for ln in col)
    typical = deficits[len(deficits) // 2]
    return right_edge, 3 * typical + 2 * statistics.median(ln["font_size"] for ln in col)


def _reflow_column(col: list[Line]) -> list[Paragraph]:
    per_size, default_gap = _gap_thresholds(col)
    use_deficit = len(col) >= 3
    if use_deficit:
        right_edge, max_deficit = _short_line_deficit(col)

    paragraphs: list[Paragraph] = []
    current: Paragraph | None = None
    prev: Line | None = None
    for ln in col:
        line_gap = per_size.get(round(ln["font_size"]), default_gap)
        new_para = (
            current is None
            or prev is None
            or (ln["y0"] - prev["y0"]) > line_gap * PARA_GAP_RATIO
            or abs(ln["font_size"] - current["font_size"]) > 1.0
            # Deficit rule only on a real row advance: PyMuPDF splits one
            # visual line into fragments at font changes (italic names), and
            # fragments end mid-row without ending a paragraph.
            or (
                use_deficit
                and ln["y0"] - prev["y0"] > 0.5 * prev["font_size"]
                and right_edge - prev["x1"] > max_deficit
            )
        )
        if new_para:
            if current:
                paragraphs.append(current)
            current = Paragraph(
                text=ln["text"], page=ln["page"], font_size=ln["font_size"], is_heading=False
            )
        else:
            current["text"] = _join(current["text"], ln["text"])
        prev = ln
    if current:
        paragraphs.append(current)
    return paragraphs


def _merge_continuations(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Stitch paragraphs split across column/page boundaries: the previous
    one ends mid-sentence and the next starts like a continuation (lowercase
    for English, a Han character for Chinese). Headings never participate."""
    merged: list[Paragraph] = []
    for para in paragraphs:
        if merged:
            prev = merged[-1]
            continues = para["text"][:1].islower() or (
                bool(_HAN_RE.match(para["text"][:1]))
                and bool(_HAN_RE.match(prev["text"][-1:]))
            )
            continuation = (
                not prev["is_heading"]
                and not para["is_heading"]
                and not prev["text"].endswith(_TERMINAL_PUNCT)
                and continues
                and abs(prev["font_size"] - para["font_size"]) <= 1.0
            )
            if continuation:
                prev["text"] = _join(prev["text"], para["text"])
                continue
        merged.append(para)
    return merged


def _mark_headings(paragraphs: list[Paragraph]) -> None:
    """Headings are noticeably larger than the length-weighted body font."""
    sizes = [p["font_size"] for p in paragraphs for _ in range(len(p["text"]))]
    if not sizes:
        return
    body_size = statistics.median(sizes)
    for p in paragraphs:
        p["is_heading"] = p["font_size"] >= body_size + 1.5 and len(p["text"]) < 120


def reflow(lines: list[Line]) -> list[Paragraph]:
    """Turn noise-stripped lines into ordered paragraphs with headings marked."""
    paragraphs: list[Paragraph] = []
    for page in sorted({ln["page"] for ln in lines}):
        page_lines = [ln for ln in lines if ln["page"] == page]
        for col in _cluster_columns(page_lines):
            paragraphs.extend(_reflow_column(col))
    # Headings are marked before continuation merging so that a heading is
    # never stitched into an adjacent paragraph.
    _mark_headings(paragraphs)
    return _merge_continuations(paragraphs)
