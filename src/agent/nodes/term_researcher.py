"""Research standard translations for unknown terms via web search.

For each candidate term one Tavily search runs with a style-shaped query
(spec 3.3.3), then a single LLM call resolves all terms at once from the
collected snippets — search results must influence the outcome, not just be
logged. Failure policy (spec 5.3): if search fails for a term, the LLM's own
best guess is used and tagged `llm_fallback` so it can be reviewed manually;
if resolution fails entirely, translation proceeds without the new terms.
"""

from src.agent.state import ArticleState
from src.tools.llm_json import loads_with_repair, strip_fences
from src.config import get_chat_model
from src.tools.web_search_tool import SearchUnavailableError, search_term

_QUERY_CONTEXT = {
    "economist": "中文翻译 经济学人 财经报道",
    "academy": "中文翻译 术语 人工智能 学术论文",
}

_RESOLVE_PROMPT = """\
You are curating a terminology glossary used to translate {style}-style
articles into Simplified Chinese. Resolve the standard Chinese translation
for each term below. Web search snippets are provided where available —
prefer the translation established in those sources. For terms marked
(no search results) use your own best knowledge.
{style_note}

{sections}

Return ONLY a JSON object mapping each English term to
{{"zh": "<translation>", "category": "<short-english-category>"}}.
"""

_STYLE_NOTES = {
    "economist": "Translate everything into Chinese; acronyms get the Chinese "
    "term with the acronym in parentheses, e.g. 首次公开募股（IPO）.",
    "academy": "Follow CS/AI community convention: if a term is normally left "
    "in English (model names, benchmark names, jargon like token/SOTA), return "
    "the English term itself as zh.",
}


def term_researcher(state: ArticleState) -> dict:
    candidates = state.get("term_candidates", [])
    if not candidates:
        return {}
    style = state["base_style"]
    errors: list[str] = []
    usage: list[dict] = []

    digests: dict[str, str | None] = {}
    for term in candidates:
        query = f'"{term}" {_QUERY_CONTEXT.get(style, "中文翻译")}'
        try:
            digests[term] = search_term(query)
        except SearchUnavailableError as exc:
            digests[term] = None
            errors.append(f"term_researcher[{term}]: {exc}; falling back to LLM guess")

    sections = "\n\n".join(
        f"### {term}\n{digest or '(no search results)'}" for term, digest in digests.items()
    )
    prompt = _RESOLVE_PROMPT.format(
        style=style, style_note=_STYLE_NOTES.get(style, ""), sections=sections
    )
    llm = get_chat_model(
        max_tokens=1024, model_kwargs={"response_format": {"type": "json_object"}}
    )

    resolved: list[dict] = []
    try:
        resp = llm.invoke(prompt)
        u = resp.usage_metadata or {}
        usage.append(
            {
                "node": "term_researcher",
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
            }
        )
        raw = loads_with_repair(strip_fences(resp.content))
        for term in candidates:
            entry = raw.get(term)
            if not isinstance(entry, dict) or not str(entry.get("zh", "")).strip():
                continue
            resolved.append(
                {
                    "en": term,
                    "zh": str(entry["zh"]).strip(),
                    "category": str(entry.get("category", "uncategorized")).strip(),
                    "source": "web_search" if digests[term] else "llm_fallback",
                }
            )
    except Exception as exc:
        errors.append(
            f"term_researcher[{state['article']['title'][:40]}]: resolution failed "
            f"({exc}); translating with existing glossary only"
        )

    return {"term_candidates": [], "resolved_terms": resolved, "errors": errors, "token_usage": usage}
