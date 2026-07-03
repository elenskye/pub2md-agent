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

_TERMINAL_PUNCT = tuple('.!?"”’…:;)')
_DATE_RE = re.compile(r"^\d{4}[./-]\d{1,2}[./-]\d{1,2}$")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿　-〿！-～]")
_HAN_RE = re.compile(r"[一-鿿㐀-䶿]")


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
                text = "".join(span["text"] for span in ln["spans"]).strip()
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


def is_page_number(line: Line, page: PageGeometry) -> bool:
    return line["text"].isdigit() and len(line["text"]) <= 4 and line["y0"] > 0.85 * page["height"]


def is_header_furniture(line: Line, page: PageGeometry) -> bool:
    """Mastheads like an issue date sitting in the top strip of a page."""
    return bool(_DATE_RE.match(line["text"])) and line["y1"] < 0.15 * page["height"]


def strip_noise(lines: list[Line], pages: list[PageGeometry]) -> list[Line]:
    """Drop page numbers, header furniture, repeated short furniture lines,
    and CJK-majority lines (any pre-existing Chinese translation is discarded
    per spec — we always re-translate from the English source)."""
    # Short lines repeating verbatim on 3+ pages are running headers/footers.
    seen_pages: dict[str, set[int]] = {}
    for ln in lines:
        if len(ln["text"]) <= 20:
            seen_pages.setdefault(ln["text"], set()).add(ln["page"])
    repeated = {t for t, ps in seen_pages.items() if len(ps) >= 3 and not t[0].isalpha()}

    kept = []
    for ln in lines:
        page = pages[ln["page"]]
        if is_page_number(ln, page) or is_header_furniture(ln, page):
            continue
        if ln["text"] in repeated:
            continue
        if is_chinese_line(ln["text"]):
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
    return prev + " " + nxt


def _reflow_column(col: list[Line]) -> list[Paragraph]:
    gaps = [b["y0"] - a["y0"] for a, b in zip(col, col[1:]) if b["y0"] > a["y0"]]
    line_gap = statistics.median(gaps) if gaps else col[0]["font_size"] * 1.4
    threshold = line_gap * PARA_GAP_RATIO

    paragraphs: list[Paragraph] = []
    current: Paragraph | None = None
    prev: Line | None = None
    for ln in col:
        new_para = (
            current is None
            or prev is None
            or (ln["y0"] - prev["y0"]) > threshold
            or abs(ln["font_size"] - current["font_size"]) > 1.0
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
    """Stitch paragraphs split across column/page boundaries: previous one
    ends mid-sentence and the next starts lowercase."""
    merged: list[Paragraph] = []
    for para in paragraphs:
        if merged:
            prev = merged[-1]
            continuation = (
                not prev["text"].endswith(_TERMINAL_PUNCT)
                and para["text"][:1].islower()
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
    paragraphs = _merge_continuations(paragraphs)
    _mark_headings(paragraphs)
    return paragraphs
