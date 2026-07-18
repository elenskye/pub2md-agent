"""Translate one article's paragraphs into Simplified Chinese.

Paragraphs are sent in numbered batches (cost control: bounded prompts,
bounded max_tokens) and the reply must echo every number back as JSON, which
guarantees EN/ZH alignment. Failure policy (spec 5.3): each batch gets up to
2 retries; paragraphs still failing are kept in English and marked
[translation failed] so the rest of the article survives.
"""

from pathlib import Path

from src.agent.state import ArticleState
from src.config import get_chat_model
from src.tools.llm_json import loads_with_repair, strip_fences
from src.tools.pdf_layout_parser import is_non_prose

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_BATCH_MAX_PARAS = 8
_BATCH_MAX_CHARS = 2400
_MAX_ATTEMPTS = 3  # 1 try + 2 retries

FAILED_MARK = "[translation failed]"

_USER_TEMPLATE = """\
Translate each numbered segment below into Simplified Chinese.
Return ONLY a JSON object mapping every segment number to its translation,
e.g. {{"1": "...", "2": "..."}}. Do not merge, split, skip or add segments.

{segments}
"""


def _load_style_prompt(style: str) -> str:
    return (_PROMPTS_DIR / f"{style}_style.md").read_text(encoding="utf-8")


def _batches(items: list[str], indices: list[int]) -> list[list[int]]:
    """Split the given segment indices into batches bounded by count/chars."""
    batches: list[list[int]] = [[]]
    chars = 0
    for i in indices:
        text = items[i]
        if batches[-1] and (len(batches[-1]) >= _BATCH_MAX_PARAS or chars + len(text) > _BATCH_MAX_CHARS):
            batches.append([])
            chars = 0
        batches[-1].append(i)
        chars += len(text)
    return [b for b in batches if b]


def _glossary_constraints(glossary: dict, text: str, limit: int = 40) -> str:
    """Constraint block for the system prompt, restricted to glossary terms
    that actually occur in this article (cost control: the glossary grows
    across runs, the prompt must not grow with it)."""
    lower = text.lower()
    hits = [t for key, t in sorted(glossary.items()) if key in lower][:limit]
    if not hits:
        return ""
    lines = "\n".join(f"- {t['en']} => {t['zh']}" for t in hits)
    return (
        "\n\nGlossary — use these exact translations for these terms, "
        "without exception:\n" + lines
    )


def _parse_reply(content: str, expected: list[int]) -> dict[int, str]:
    raw = loads_with_repair(strip_fences(content))
    out = {int(k): str(v).strip() for k, v in raw.items()}
    missing = [i for i in expected if i + 1 not in out or not out[i + 1]]
    if missing:
        raise ValueError(f"segments missing from reply: {[i + 1 for i in missing]}")
    return out


def translator(state: ArticleState) -> dict:
    article = state["article"]
    style = state["base_style"]
    # JSON mode: the API guarantees well-formed JSON, which plain prompting
    # does not (observed failures: bare newlines, missing closing quotes).
    llm = get_chat_model(model_kwargs={"response_format": {"type": "json_object"}})

    # Title and standfirst are translated alongside the body in batch 1.
    segments = [article["title"]] + ([article["subtitle"]] if article["subtitle"] else [])
    n_meta = len(segments)
    body = state.get("english_paragraphs", article["paragraphs"])
    flags = state.get("english_headings") or article.get("headings") or [False] * len(body)
    segments += body
    heading_of = {n_meta + k: flag for k, flag in enumerate(flags)}

    # Formula debris and reference wraps pass through verbatim — sending
    # "(3)" or "i i i" to the model wastes tokens and invites garbling.
    # Headings are always translated regardless of shape.
    verbatim = {
        i
        for i in range(n_meta, len(segments))
        if not heading_of.get(i) and is_non_prose(segments[i])
    }
    translatable = [i for i in range(len(segments)) if i not in verbatim]

    system = _load_style_prompt(style) + _glossary_constraints(
        state.get("glossary", {}), "\n".join(segments)
    )

    zh: dict[int, str] = {}
    errors: list[str] = []
    usage: list[dict] = []

    for batch in _batches(segments, translatable):
        numbered = "\n\n".join(f"[{i + 1}] {segments[i]}" for i in batch)
        prompt = _USER_TEMPLATE.format(segments=numbered)
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = llm.invoke([("system", system), ("user", prompt)])
                u = resp.usage_metadata or {}
                usage.append(
                    {
                        "node": "translator",
                        "input_tokens": u.get("input_tokens", 0),
                        "output_tokens": u.get("output_tokens", 0),
                    }
                )
                parsed = _parse_reply(resp.content, batch)
                zh.update({i: parsed[i + 1] for i in batch})
                break
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS - 1:
                    errors.append(
                        f"translator[{article['title'][:40]}]: batch of "
                        f"{len(batch)} segments failed after {_MAX_ATTEMPTS} attempts: {exc}"
                    )

    pairs = []
    for i in range(n_meta, len(segments)):
        if i in verbatim:
            pairs.append(
                {"en": segments[i], "zh": segments[i], "failed": False, "is_heading": False}
            )
        else:
            pairs.append(
                {
                    "en": segments[i],
                    "zh": zh.get(i, FAILED_MARK),
                    "failed": i not in zh,
                    "is_heading": bool(heading_of.get(i)),
                }
            )
    return {
        "zh_title": zh.get(0, FAILED_MARK),
        "zh_subtitle": zh.get(1, FAILED_MARK) if article["subtitle"] else "",
        "translated_paragraphs": pairs,
        "output_mode": "bilingual",
        "errors": errors,
        "token_usage": usage,
    }
