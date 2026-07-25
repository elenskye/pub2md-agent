"""VLM layout hybrid: reading order + block roles from a vision model.

The geometric column clustering in pdf_layout_parser breaks on pages with
column-spanning floats (observed: zipped columns on the Pargent paper).
This module fixes reading order the robust way: each page is rendered to
an image with its TEXT-LAYER blocks outlined and numbered, and the VLM
answers only two questions — in what order should the blocks be read, and
what role does each block play. The text itself always comes from the PDF
text layer, so there is zero transcription risk.

Non-body blocks (author strips, captions, tables, footnotes, references,
furniture) are dropped right here; the body_gatekeeper downstream stays as
a second, cheaper net for whatever the VLM mislabels.

Fail-open on every level: VLM unconfigured → feature off entirely
(VLM_LAYOUT env can also force "off"); a failed or implausible per-page
answer keeps that page on the geometric path. Pages are classified
concurrently (VLM_LAYOUT_CONCURRENCY, default 4).
"""

import base64
import os
from concurrent.futures import ThreadPoolExecutor

import pymupdf

from src.agent.state import Line
from src.config import get_vlm_model, load_vlm_settings
from src.tools.llm_json import loads_with_repair, strip_fences
from src.tools.progress import ProgressTracker

_DPI = 140  # red block labels must stay legible to the small VLM
# Ordered blocks must cover this share of the page's CHARACTERS, else the
# page falls back to geometry. Character-based, not block-based: the small
# VLM habitually omits tiny furniture/reference blocks from "order", which
# is harmless (they are appended geometrically and usually dropped later),
# while a genuinely nonsensical answer still fails the volume check.
_MIN_COVERAGE = 0.6
_KEEP_ROLES = {"body", "heading", "title", "abstract"}
_ALL_ROLES = _KEEP_ROLES | {"author", "caption", "table", "footnote", "reference", "furniture"}

_PROMPT = """\
This is one page of a PDF (magazine or academic paper). Every text block
is outlined in red and labelled with a number at its top-left corner.
The blocks present on this page are exactly: {block_list}.

Return ONLY a JSON object:
{"order": [<ALL block numbers in natural reading order>],
 "roles": {"<number>": "<role>", ...}}

"roles" lists ONLY the blocks that are NOT normal article body — do not
list body blocks (anything absent from "roles" counts as body). Non-body
roles: heading (section heading/crosshead), title (article title),
abstract, author (author names, affiliations, correspondence), caption
(figure/table captions or text inside figures), table (tabular data),
footnote (footnotes, funding, acknowledgements), reference (bibliography
entries), furniture (journal branding, page headers/footers, keywords/DOI
lines, license notices).

Reading order rules: title, then the text flow — in multi-column layouts
finish the left column before starting the right one. Include EVERY
numbered block exactly once in "order"; "order" must be complete even for
blocks you list in "roles".
"""


def enabled() -> bool:
    return load_vlm_settings() is not None and os.getenv("VLM_LAYOUT", "on").lower() != "off"


def _page_blocks(page_lines: list[Line]) -> dict[int, tuple[float, float, float, float]]:
    """Block id → bounding box over that block's lines."""
    boxes: dict[int, tuple[float, float, float, float]] = {}
    for ln in page_lines:
        b = ln.get("block", -1)
        x0, y0, x1, y1 = ln["x0"], ln["y0"], ln["x1"], ln["y1"]
        if b in boxes:
            bx0, by0, bx1, by1 = boxes[b]
            boxes[b] = (min(bx0, x0), min(by0, y0), max(bx1, x1), max(by1, y1))
        else:
            boxes[b] = (x0, y0, x1, y1)
    return boxes


def _annotated_png(doc: pymupdf.Document, pno: int, boxes: dict[int, tuple]) -> bytes:
    page = doc[pno]
    shape = page.new_shape()
    for b, (x0, y0, x1, y1) in boxes.items():
        shape.draw_rect(pymupdf.Rect(x0, y0, x1, y1) + (-2, -2, 2, 2))
    shape.finish(color=(0.85, 0.1, 0.1), width=1.2)
    shape.commit()
    for b, (x0, y0, _, _) in boxes.items():
        page.insert_text(
            pymupdf.Point(max(x0 - 1, 2), max(y0 - 3, 10)),
            str(b),
            fontsize=9,
            color=(0.85, 0.1, 0.1),
        )
    return page.get_pixmap(dpi=_DPI).tobytes("png")


def _parse_answer(content: str, block_chars: dict[int, int]) -> tuple[list[int], dict[int, str]]:
    raw = loads_with_repair(strip_fences(content))
    order = [int(b) for b in raw.get("order", []) if int(b) in block_chars]
    order = list(dict.fromkeys(order))  # dedupe, keep first occurrence
    roles: dict[int, str] = {}
    for key, value in raw.get("roles", {}).items():
        b = int(key)
        if b in block_chars and str(value) in _ALL_ROLES:
            roles[b] = str(value)
    # Coverage counts every block the model ACCOUNTED FOR — ordered or
    # role-labelled. The small VLM treats the two lists as complementary
    # (a block it labels caption/author often never enters "order"), which
    # is fine: blocks we are about to drop don't need an order.
    accounted = set(order) | set(roles)
    covered = sum(block_chars[b] for b in accounted)
    total = sum(block_chars.values()) or 1
    if covered < _MIN_COVERAGE * total:
        raise ValueError(
            f"answer accounts for only {covered}/{total} chars "
            f"({len(accounted)}/{len(block_chars)} blocks)"
        )
    return order, roles


def _order_one_page(
    pdf_path: str, pno: int, page_lines: list[Line], vlm
) -> tuple[list[Line], dict, dict[str, int]]:
    """VLM-ordered lines for one page. Raises on failure (caller falls
    back to geometry). Returns (ordered lines, usage, dropped-role counts).
    Opens its own document: page annotation mutates the in-memory doc and
    pymupdf documents are not safe to share across worker threads."""
    boxes = _page_blocks(page_lines)
    with pymupdf.open(pdf_path) as doc:
        png = _annotated_png(doc, pno, boxes)
    # .replace, not .format: the prompt body contains literal JSON braces.
    prompt = _PROMPT.replace("{block_list}", ", ".join(str(b) for b in sorted(boxes)))
    resp = vlm.invoke(
        [
            (
                "user",
                [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
                    },
                ],
            )
        ]
    )
    u = resp.usage_metadata or {}
    usage = {
        "node": "vlm_layout",
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
    }
    block_chars: dict[int, int] = {}
    for ln in page_lines:
        b = ln.get("block", -1)
        block_chars[b] = block_chars.get(b, 0) + len(ln["text"])
    order, roles = _parse_answer(resp.content, block_chars)
    # Blocks the model forgot keep their geometric position at the end —
    # losing text silently is worse than a slightly odd order.
    order += [b for b in boxes if b not in order]
    # The article title always reads first on its page: anything the model
    # ordered before it (journal strips, section labels) would otherwise
    # split off as an "untitled article" in segmentation.
    order.sort(key=lambda b: 0 if roles.get(b) == "title" else 1)

    by_block: dict[int, list[Line]] = {}
    for ln in page_lines:
        by_block.setdefault(ln.get("block", -1), []).append(ln)

    ordered: list[Line] = []
    dropped: dict[str, int] = {}
    for b in order:
        role = roles.get(b, "body")
        if role in _KEEP_ROLES:
            ordered.extend(sorted(by_block.get(b, []), key=lambda ln: (ln["y0"], ln["x0"])))
        else:
            dropped[role] = dropped.get(role, 0) + 1
    return ordered, usage, dropped


def resolve_reading_order(
    lines: list[Line], pdf_path: str, tracker: ProgressTracker | None = None
) -> tuple[list[Line], set[int], list[dict], list[str]]:
    """Reorder all pages' lines via the VLM. Returns (lines, vlm_pages,
    token_usage, errors); pages not in vlm_pages keep geometric handling
    downstream. The input list is returned unchanged when the feature is
    disabled."""
    if not enabled():
        return lines, set(), [], []

    # 2048: an "order" list for a dense page plus its non-body roles must
    # never hit the token ceiling — truncated JSON was the main cause of
    # geometric fallbacks in the first verification round.
    vlm = get_vlm_model(load_vlm_settings(), max_tokens=2048)
    page_numbers = sorted({ln["page"] for ln in lines})
    if tracker:
        tracker.add_total("layout", len(page_numbers))

    def _one(pno: int):
        page_lines = [ln for ln in lines if ln["page"] == pno]
        try:
            return pno, _order_one_page(pdf_path, pno, page_lines, vlm), None
        except Exception as exc:  # noqa: BLE001 — per-page fail-open
            return pno, None, f"vlm_layout[p{pno}]: {exc}; geometric fallback for this page"
        finally:
            if tracker:
                tracker.add_done("layout")

    workers = max(1, int(os.getenv("VLM_LAYOUT_CONCURRENCY", "4")))
    results: dict[int, list[Line]] = {}
    usage: list[dict] = []
    errors: list[str] = []
    dropped_total: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for pno, ok, err in pool.map(_one, page_numbers):
            if ok is None:
                errors.append(err)
                continue
            ordered, u, dropped = ok
            results[pno] = ordered
            usage.append(u)
            for role, n in dropped.items():
                dropped_total[role] = dropped_total.get(role, 0) + n

    if dropped_total:
        detail = ", ".join(f"{v} {k}" for k, v in sorted(dropped_total.items()))
        errors.append(f"vlm_layout: dropped non-body blocks ({detail})")

    out: list[Line] = []
    for pno in page_numbers:
        if pno in results:
            out.extend(results[pno])
        else:
            out.extend(ln for ln in lines if ln["page"] == pno)
    return out, set(results), usage, errors
