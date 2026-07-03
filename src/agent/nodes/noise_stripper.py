"""Strip PDF furniture and reflow lines into clean paragraphs.

Drops page numbers and header furniture; in majority-English documents also
drops any embedded Chinese translation (always discarded per spec 3.1 — we
re-translate from the English source), then merges lines into paragraphs
using vertical-gap and font-size cues. Majority-Chinese documents keep their
text and are routed per-article to the OpenCC path downstream.
"""

from src.agent.state import PipelineState
from src.tools.pdf_layout_parser import drop_embedded_translation, reflow, strip_noise


def noise_stripper(state: PipelineState) -> dict:
    kept = strip_noise(state["raw_blocks"], state["page_sizes"])
    kept = drop_embedded_translation(kept)
    return {"cleaned_text": reflow(kept)}
