"""Keep only body text: the LLM half of the v3 output-purity rule.

Runs after en_text_isolator. First the deterministic filters strip
references, captions and marker-matching furniture for free; then the
surviving paragraphs are classified by the LLM in batches and everything
that is not article body (author blocks, journal furniture the regexes
can't see) is dropped.

Same generate-critique pattern as the terminology gates — deliberately a
single classifier node, not a multi-agent system (owner decision).
Failure policy: fail open per batch — a failed call keeps its paragraphs,
so the worst case equals the pre-Phase-3 behaviour.

Display formulas are auto-kept and never sent to the LLM. Headings ARE
classified: author bylines under the title routinely carry heading-grade
styling, so a heading exemption would wave exactly the junk through that
this node exists to stop (observed on the Pargent paper). Snippets are
truncated for classification: the label depends on how a paragraph
starts, not on reading all of it.
"""

from src.agent.state import ArticleState
from src.config import get_chat_model
from src.tools.body_filters import deterministic_filter, is_formula
from src.tools.llm_json import loads_with_repair, strip_fences
from src.tools.progress import tracker_from

_BATCH = 40
_SNIPPET_CHARS = 200

_LABELS = {"body", "author_block", "caption", "footnote", "reference", "furniture"}

_PROMPT = """\
You are cleaning an article extracted from a PDF before translation. For
each numbered snippet decide whether it belongs to the article's BODY.

Labels:
- body: prose paragraphs, section headings/crossheads, list items, the
  abstract
- author_block: author names, affiliations, universities, correspondence
- caption: figure/table captions or text lifted from a figure
- footnote: footnotes, acknowledgements, funding or availability notes
- reference: bibliography entries
- furniture: journal/brand names, keywords lines, page furniture, dates
  received/accepted, anything else that is not article body

Snippets:
{snippets}

Return ONLY a JSON object mapping every snippet number to its label,
e.g. {{"1": "body", "2": "furniture"}}.
"""


def _classify(indices: list[int], paragraphs: list[str]) -> tuple[dict[int, str], dict]:
    """One LLM call over the given paragraph indices. Raises on failure."""
    llm = get_chat_model(
        max_tokens=1024, model_kwargs={"response_format": {"type": "json_object"}}
    )
    snippets = "\n".join(
        f"[{k + 1}] {paragraphs[i][:_SNIPPET_CHARS]}" for k, i in enumerate(indices)
    )
    resp = llm.invoke(_PROMPT.format(snippets=snippets))
    u = resp.usage_metadata or {}
    usage = {
        "node": "body_gatekeeper",
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
    }
    raw = loads_with_repair(strip_fences(resp.content))
    labels: dict[int, str] = {}
    for key, value in raw.items():
        k = int(key) - 1
        if 0 <= k < len(indices) and str(value) in _LABELS:
            labels[indices[k]] = str(value)
    return labels, usage


def body_gatekeeper(state: ArticleState, config=None) -> dict:
    article = state["article"]
    tracker = tracker_from(config)
    paragraphs = state.get("english_paragraphs", [])
    headings = state.get("english_headings") or [False] * len(paragraphs)

    paragraphs, headings, removed = deterministic_filter(paragraphs, headings)

    # Everything except display formulas is classified — including headings
    # (author bylines often carry heading styling) and the standfirst: the
    # segmenter takes the bold line under an academic paper's title as the
    # subtitle, which is routinely the author byline.
    to_judge = [i for i, t in enumerate(paragraphs) if not is_formula(t)]
    subtitle = article.get("subtitle", "")
    subtitle_index = -1
    if subtitle:
        subtitle_index = len(paragraphs)
        paragraphs = [*paragraphs, subtitle]
        to_judge.append(subtitle_index)

    batches = [to_judge[start : start + _BATCH] for start in range(0, len(to_judge), _BATCH)]
    if tracker:
        tracker.add_total("gatekeeper", len(batches))

    errors: list[str] = []
    usage: list[dict] = []
    labels: dict[int, str] = {}
    for batch in batches:
        try:
            batch_labels, u = _classify(batch, paragraphs)
            labels.update(batch_labels)
            usage.append(u)
        except Exception as exc:
            errors.append(
                f"body_gatekeeper[{article['title'][:40]}]: classification batch "
                f"failed ({exc}); keeping its {len(batch)} paragraph(s)"
            )
        finally:
            if tracker:
                tracker.add_done("gatekeeper")

    kept_p: list[str] = []
    kept_h: list[bool] = []
    for i, (text, heading) in enumerate(zip(paragraphs, headings)):
        label = labels.get(i, "body")  # unruled → fail open
        if label == "body":
            kept_p.append(text)
            kept_h.append(heading)
        else:
            removed[label] = removed.get(label, 0) + 1

    out: dict = {}
    subtitle_label = labels.get(subtitle_index, "body")
    if subtitle_index >= 0 and subtitle_label != "body":
        removed[subtitle_label] = removed.get(subtitle_label, 0) + 1
        out["article"] = {**article, "subtitle": ""}

    total = sum(removed.values())
    if total:
        detail = ", ".join(f"{v} {k}" for k, v in sorted(removed.items()) if v)
        errors.append(
            f"body_gatekeeper[{article['title'][:40]}]: removed {total} "
            f"non-body paragraph(s) ({detail})"
        )

    return {
        **out,
        "english_paragraphs": kept_p,
        "english_headings": kept_h,
        "errors": errors,
        "token_usage": usage,
    }
