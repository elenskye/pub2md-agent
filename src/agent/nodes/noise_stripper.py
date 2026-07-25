"""Strip PDF furniture and reflow lines into clean paragraphs.

Drops page numbers and header furniture; in majority-English documents also
drops any embedded Chinese translation (always discarded per spec 3.1 — we
re-translate from the English source). Reading order is then resolved by
the VLM layout hybrid when configured (per-page fail-open to the geometric
column clustering), and lines are merged into paragraphs using
vertical-gap and font-size cues. Majority-Chinese documents keep their
text and are routed per-article to the OpenCC path downstream.
"""

from src.agent.state import PipelineState
from src.tools.pdf_layout_parser import (
    drop_embedded_translation,
    mask_special_regions,
    reflow,
    strip_noise,
)
from src.tools.progress import tracker_from
from src.tools.vlm_layout import resolve_reading_order


def noise_stripper(state: PipelineState, config=None) -> dict:
    kept = strip_noise(state["raw_blocks"], state["page_sizes"])
    kept = drop_embedded_translation(kept)
    kept = mask_special_regions(kept, state["page_sizes"])
    kept, vlm_pages, usage, errors = resolve_reading_order(
        kept, state["pdf_path"], tracker_from(config)
    )
    return {
        "cleaned_text": reflow(kept, vlm_pages),
        "errors": errors,
        "token_usage": usage,
    }
