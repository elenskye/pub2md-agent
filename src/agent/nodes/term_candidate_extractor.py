"""Find specialized terms in the article that the glossary does not cover.

The LLM sees the article text (capped) plus the list of already-known
glossary terms, and returns only NEW candidates — scoping against the loaded
glossary avoids re-researching the same terms every run (spec 3.4). Failure
here degrades gracefully: no candidates means translation proceeds with the
existing glossary only.
"""

from src.agent.state import ArticleState
from src.tools.llm_json import loads_with_repair, strip_fences
from src.config import get_chat_model

_MAX_TEXT_CHARS = 6000
_MAX_CANDIDATES = 8

_PROMPT = """\
You are preparing a terminology glossary for translating an article into
Simplified Chinese ({style} style). Below is the article text and the list
of terms the glossary already covers.

List up to {max_candidates} specialized terms (economics/finance/technology
jargon, institutions, recurring coined phrases) from the article that are
NOT already covered and whose translation should stay consistent across
articles. Exclude: plain everyday words, person names, place names, and
anything already in the known list.

Known glossary terms:
{known}

Article text:
{text}

Return ONLY a JSON object: {{"terms": ["...", ...]}} (empty list if none).
"""


def term_candidate_extractor(state: ArticleState) -> dict:
    article = state["article"]
    glossary = state.get("glossary", {})
    text = "\n".join([article["title"], article["subtitle"], *state["english_paragraphs"]])
    text = text[:_MAX_TEXT_CHARS]
    known = ", ".join(sorted(t["en"] for t in glossary.values())) or "(empty)"

    llm = get_chat_model(
        max_tokens=512, model_kwargs={"response_format": {"type": "json_object"}}
    )
    prompt = _PROMPT.format(
        style=state["style"], max_candidates=_MAX_CANDIDATES, known=known, text=text
    )

    candidates: list[str] = []
    errors: list[str] = []
    usage: list[dict] = []
    try:
        resp = llm.invoke(prompt)
        u = resp.usage_metadata or {}
        usage.append(
            {
                "node": "term_candidate_extractor",
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
            }
        )
        raw = loads_with_repair(strip_fences(resp.content))
        candidates = [
            t.strip()
            for t in raw.get("terms", [])
            if isinstance(t, str) and t.strip() and t.strip().lower() not in glossary
        ][:_MAX_CANDIDATES]
    except Exception as exc:
        errors.append(
            f"term_candidate_extractor[{article['title'][:40]}]: {exc}; "
            "continuing with existing glossary only"
        )

    return {"term_candidates": candidates, "errors": errors, "token_usage": usage}
