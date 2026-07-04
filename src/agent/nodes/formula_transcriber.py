"""Transcribe display-formula regions to LaTeX via a multimodal model.

Runs at the document level (between noise_stripper and article_segmenter):
each formula paragraph carries a page + crop rect from layout analysis; the
region is rendered to PNG and sent to the configured VLM, and the paragraph
text becomes a $$...$$ block that downstream nodes pass through verbatim.

Degradation ladder (spec 5.3 spirit):
- VLM unconfigured (no VLM_* env) → fenced code block with the raw glyph
  text, marked [formula]; the run works end-to-end without a VLM.
- VLM call fails for one region → same placeholder for that region only.
Table regions were already replaced by "[table omitted]" placeholders in
layout analysis; this node leaves them as-is.
"""

import base64

import pymupdf

from src.agent.state import PipelineState
from src.config import get_vlm_model, load_vlm_settings

_MAX_FORMULAS = 30
_DPI = 200
_PAD = 4.0

_PROMPT = (
    "Transcribe the formula in this image to LaTeX. Return ONLY the raw "
    "LaTeX code, no surrounding $$, no code fences, no commentary."
)


def _placeholder(text: str) -> str:
    return f"```\n[formula] {text}\n```"


def _crop_png(doc: pymupdf.Document, page: int, clip: tuple) -> bytes:
    rect = pymupdf.Rect(*clip) + (-_PAD, -_PAD, _PAD, _PAD)
    pix = doc[page].get_pixmap(clip=rect, dpi=_DPI)
    return pix.tobytes("png")


def formula_transcriber(state: PipelineState) -> dict:
    paragraphs = state["cleaned_text"]
    formulas = [p for p in paragraphs if p.get("special") == "formula"]
    if not formulas:
        return {}

    errors: list[str] = []
    usage: list[dict] = []
    vlm_settings = load_vlm_settings()
    if vlm_settings is None:
        for p in formulas:
            p["text"] = _placeholder(p["text"])
        errors.append(
            f"formula_transcriber: VLM_* not configured; left {len(formulas)} "
            "formula(s) as placeholders"
        )
        return {"cleaned_text": paragraphs, "errors": errors}

    vlm = get_vlm_model(vlm_settings)
    doc = pymupdf.open(state["pdf_path"])
    for n, p in enumerate(formulas):
        if n >= _MAX_FORMULAS:
            p["text"] = _placeholder(p["text"])
            continue
        try:
            png = _crop_png(doc, p["page"], p["clip"])
            image_b64 = base64.b64encode(png).decode()
            resp = vlm.invoke(
                [
                    (
                        "user",
                        [
                            {"type": "text", "text": _PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                            },
                        ],
                    )
                ]
            )
            u = resp.usage_metadata or {}
            usage.append(
                {
                    "node": "formula_transcriber",
                    "input_tokens": u.get("input_tokens", 0),
                    "output_tokens": u.get("output_tokens", 0),
                }
            )
            latex = resp.content.strip().strip("$").strip()
            latex = latex.removeprefix("```latex").removeprefix("```").removesuffix("```").strip()
            if not latex:
                raise ValueError("empty transcription")
            # Delimiters on their own lines: block-math form many Markdown
            # note apps require to recognise the formula as display math.
            p["text"] = f"$$\n{latex}\n$$"
        except Exception as exc:
            errors.append(
                f"formula_transcriber[p{p['page']}]: {exc}; keeping placeholder"
            )
            p["text"] = _placeholder(p["text"])
    doc.close()
    if len(formulas) > _MAX_FORMULAS:
        errors.append(
            f"formula_transcriber: {len(formulas) - _MAX_FORMULAS} formula(s) beyond "
            f"the cap of {_MAX_FORMULAS} left as placeholders"
        )
    return {"cleaned_text": paragraphs, "errors": errors, "token_usage": usage}
