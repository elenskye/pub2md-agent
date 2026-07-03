"""Extract line-level text blocks with coordinates from the input PDF.

Failure policy (spec 5.3): if no text layer is found, PDFExtractionError
propagates and aborts the whole run — a partial source would make every
downstream step unreliable.
"""

from src.agent.state import PipelineState
from src.tools.pdf_layout_parser import extract_lines


def pdf_extractor(state: PipelineState) -> dict:
    lines, pages = extract_lines(state["pdf_path"])
    return {"raw_blocks": lines, "page_sizes": pages}
