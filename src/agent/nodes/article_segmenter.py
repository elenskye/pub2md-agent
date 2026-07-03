"""Split the cleaned paragraph stream into articles.

Two layers (spec 5.3):
1. Rule-based candidates: paragraphs marked as headings by font size.
2. LLM confirmation: only heading text + a short preview of what follows is
   sent (never the full body — cost control, spec 4.1.3). The LLM rejects
   false positives such as chart titles or pull quotes.

Graceful degradation: if the LLM call or its JSON cannot be used after one
retry, all rule-based candidates are accepted and the error is logged.
"""

import json
from pathlib import Path

from src.agent.state import Article, Paragraph, PipelineState
from src.config import get_chat_model
from src.tools.pdf_layout_parser import latin_han_counts

_PREVIEW_CHARS = 200

_CONFIRM_PROMPT = """\
You are segmenting a magazine PDF into articles. Below are heading candidates
detected by layout analysis, each with a preview of the text that follows.
Real article headings start a new, self-contained article; reject candidates
that are chart/figure titles, pull quotes, or section labels. In particular,
a single academic paper is ONE article: its title is the only article start,
and internal section headings ("Abstract", "Introduction", "2 Background",
"Conclusion", "References", ...) must be rejected.

Candidates:
{candidates}

Return ONLY a JSON object: {{"article_start_ids": [<ids of confirmed headings, ascending>]}}
"""


def _subtitle_of(title: str, paras: list[Paragraph]) -> str:
    """The paragraph right after a title is a standfirst if it is short,
    does not end like a body sentence, and is written in the same script as
    the title (a Latin-only line under a Chinese title is leftover junk)."""
    if not paras:
        return ""
    cand = paras[0]["text"]
    if len(cand) > 160 or cand.endswith((".", "。", "！", "？")):
        return ""
    _, title_han = latin_han_counts(title)
    _, cand_han = latin_han_counts(cand)
    if title_han > 0 and cand_han == 0:
        return ""
    return cand


def _confirm_with_llm(candidates: list[dict]) -> tuple[list[int], object]:
    llm = get_chat_model(
        max_tokens=512, model_kwargs={"response_format": {"type": "json_object"}}
    )
    payload = json.dumps(candidates, ensure_ascii=False, indent=1)
    resp = llm.invoke(_CONFIRM_PROMPT.format(candidates=payload))
    text = resp.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    ids = json.loads(text, strict=False)["article_start_ids"]
    valid = {c["id"] for c in candidates}
    confirmed = sorted(i for i in ids if i in valid)
    if not confirmed:
        raise ValueError("LLM confirmed no headings")
    return confirmed, resp


def article_segmenter(state: PipelineState) -> dict:
    paras = state["cleaned_text"]
    errors: list[str] = []
    usage: list[dict] = []

    heading_idx = [i for i, p in enumerate(paras) if p["is_heading"]]

    if not heading_idx:
        # No headings at all: treat the whole document as one article.
        title = Path(state["pdf_path"]).stem
        body = [p["text"] for p in paras]
        return {
            "articles": [Article(index=0, title=title, subtitle="", paragraphs=body)],
            "errors": ["article_segmenter: no headings detected, whole PDF as one article"],
        }

    candidates = [
        {
            "id": i,
            "heading": paras[i]["text"],
            "preview": " ".join(p["text"] for p in paras[i + 1 : i + 3])[:_PREVIEW_CHARS],
        }
        for i in heading_idx
    ]

    confirmed = heading_idx
    for attempt in range(2):
        try:
            confirmed, resp = _confirm_with_llm(candidates)
            u = resp.usage_metadata or {}
            usage.append(
                {
                    "node": "article_segmenter",
                    "input_tokens": u.get("input_tokens", 0),
                    "output_tokens": u.get("output_tokens", 0),
                }
            )
            break
        except Exception as exc:
            if attempt == 1:
                errors.append(
                    f"article_segmenter: LLM confirmation failed ({exc}); "
                    "falling back to all rule-based candidates"
                )

    articles: list[Article] = []
    bounds = confirmed + [len(paras)]
    for n, (start, end) in enumerate(zip(bounds, bounds[1:])):
        title = paras[start]["text"]
        # Consecutive confirmed headings with nothing between them cannot
        # happen (previews were non-empty), but guard against empty slices.
        rest = paras[start + 1 : end]
        subtitle = _subtitle_of(title, rest)
        # Unconfirmed headings inside the slice are crossheads/callouts —
        # kept as body content, dropping them would lose text.
        body = [p["text"] for p in (rest[1:] if subtitle else rest)]
        articles.append(Article(index=n, title=title, subtitle=subtitle, paragraphs=body))

    leading = paras[: confirmed[0]]
    if sum(len(p["text"]) for p in leading) > 400:
        errors.append(
            f"article_segmenter: {len(leading)} paragraphs before the first heading "
            "were kept as an untitled article"
        )
        articles.insert(
            0,
            Article(
                index=-1,
                title=f"{Path(state['pdf_path']).stem} (untitled leading section)",
                subtitle="",
                paragraphs=[p["text"] for p in leading],
            ),
        )
        for n, a in enumerate(articles):
            a["index"] = n

    return {"articles": articles, "errors": errors, "token_usage": usage}
