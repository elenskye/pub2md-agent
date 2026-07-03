"""Strip PDF furniture and reflow lines into clean paragraphs.

Drops page numbers, header furniture and any embedded Chinese translation
(always discarded per spec 3.1 — we re-translate from the English source),
then merges lines into paragraphs using vertical-gap and font-size cues.
"""

from src.agent.state import PipelineState
from src.tools.pdf_layout_parser import reflow, strip_noise


def noise_stripper(state: PipelineState) -> dict:
    kept = strip_noise(state["raw_blocks"], state["page_sizes"])
    return {"cleaned_text": reflow(kept)}
