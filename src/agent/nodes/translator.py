"""Translate one article's paragraphs into Simplified Chinese.

Paragraphs are sent in numbered batches (cost control: bounded prompts,
bounded max_tokens) and the reply must echo every number back as JSON, which
guarantees EN/ZH alignment. Batches run concurrently in a bounded thread
pool (TRANSLATE_CONCURRENCY, default 4 — v3 Phase 3 speed work): batches
are independent by construction, so ordering only matters when results are
assembled, which stays deterministic via the index map. Failure policy
(spec 5.3): each batch gets up to 2 retries; paragraphs still failing are
kept in English and marked [translation failed] so the rest of the article
survives.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.agent.state import ArticleState
from src.config import get_chat_model
from src.tools.glossary_store import record_occurrences
from src.tools.llm_json import loads_with_repair, strip_fences
from src.tools.pdf_layout_parser import is_non_prose
from src.tools.progress import tracker_from
from src.tools.term_context import extract_example

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_BATCH_MAX_PARAS = 12
_BATCH_MAX_CHARS = 4000
_MAX_ATTEMPTS = 3  # 1 try + 2 retries

FAILED_MARK = "[translation failed]"

_USER_TEMPLATE = """\
Translate each numbered segment below into Simplified Chinese.
Return ONLY a JSON object mapping every segment number to its translation,
e.g. {{"1": "...", "2": "..."}}. Do not merge, split, skip or add segments.

{segments}
"""

# Optional second pass (state["refine"]): the draft is reviewed against the
# source under the same style/glossary constraints — one extra call per
# batch, roughly doubling translation cost and time.
_REFINE_TEMPLATE = """\
Below are numbered English segments with their draft Simplified-Chinese
translations. Review every draft against its English source and the style
rules from the system prompt: fix mistranslations, enforce the glossary,
and polish the wording into fluent written academic/journalistic Chinese.
Return ONLY a JSON object mapping every segment number to the final
translation (improved, or unchanged when the draft is already good).
Do not merge, split, skip or add segments.

{pairs}
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


def _glossary_hits(glossary: dict, text: str, limit: int = 40) -> list[dict]:
    """Glossary terms that actually occur in this article (cost control: the
    glossary grows across runs, the prompt must not grow with it)."""
    lower = text.lower()
    return [t for key, t in sorted(glossary.items()) if key in lower][:limit]


def _glossary_constraints(hits: list[dict]) -> str:
    """Constraint block for the system prompt."""
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


def translator(state: ArticleState, config=None) -> dict:
    article = state["article"]
    tracker = tracker_from(config)
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

    hits = _glossary_hits(state.get("glossary", {}), "\n".join(segments))
    system = _load_style_prompt(style) + _glossary_constraints(hits)

    # Every known-term sighting feeds the wordbook (term_occurrences):
    # frequency and real example sentences accumulate from articles the
    # user actually read. Entries without a domain (test fixtures) are
    # skipped rather than mis-attributed.
    record_occurrences(
        [
            {
                "domain": t["domain"],
                "en": t["en"],
                "article_title": article["title"],
                "sentence": extract_example(t["en"], segments),
            }
            for t in hits
            if t.get("domain")
        ]
    )

    zh: dict[int, str] = {}
    errors: list[str] = []
    usage: list[dict] = []

    def _translate_batch(batch: list[int]) -> tuple[dict[int, str], list[dict], list[str]]:
        try:
            return _translate_batch_inner(batch)
        finally:
            if tracker:
                tracker.add_done("translate", len(batch))

    def _translate_batch_inner(batch: list[int]) -> tuple[dict[int, str], list[dict], list[str]]:
        numbered = "\n\n".join(f"[{i + 1}] {segments[i]}" for i in batch)
        prompt = _USER_TEMPLATE.format(segments=numbered)
        batch_usage: list[dict] = []
        for attempt in range(_MAX_ATTEMPTS):
            try:
                resp = llm.invoke([("system", system), ("user", prompt)])
                u = resp.usage_metadata or {}
                batch_usage.append(
                    {
                        "node": "translator",
                        "input_tokens": u.get("input_tokens", 0),
                        "output_tokens": u.get("output_tokens", 0),
                    }
                )
                parsed = _parse_reply(resp.content, batch)
                return {i: parsed[i + 1] for i in batch}, batch_usage, []
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS - 1:
                    return {}, batch_usage, [
                        f"translator[{article['title'][:40]}]: batch of "
                        f"{len(batch)} segments failed after {_MAX_ATTEMPTS} attempts: {exc}"
                    ]
        return {}, batch_usage, []

    refine = bool(state.get("refine"))
    all_batches = _batches(segments, translatable)
    # Progress is counted in PARAGRAPHS (owner spec): the total is known
    # before translation starts, and each finished batch ticks its segment
    # count. The refine pass processes every paragraph again, so it
    # registers the same total a second time.
    if tracker:
        tracker.add_total("translate", len(translatable) * (2 if refine else 1))
    workers = max(1, int(os.getenv("TRANSLATE_CONCURRENCY", "4")))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch_zh, batch_usage, batch_errors in pool.map(_translate_batch, all_batches):
            zh.update(batch_zh)
            usage.extend(batch_usage)
            errors.extend(batch_errors)

    if refine:
        def _refine_batch(batch: list[int]) -> tuple[dict[int, str], list[dict], list[str]]:
            done = [i for i in batch if i in zh]
            try:
                if not done:
                    return {}, [], []
                pairs = "\n\n".join(f"[{i + 1}] EN: {segments[i]}\nZH: {zh[i]}" for i in done)
                prompt = _REFINE_TEMPLATE.format(pairs=pairs)
                refine_usage: list[dict] = []
                for attempt in range(2):  # fail-open: the draft survives
                    try:
                        resp = llm.invoke([("system", system), ("user", prompt)])
                        u = resp.usage_metadata or {}
                        refine_usage.append(
                            {
                                "node": "translator_refine",
                                "input_tokens": u.get("input_tokens", 0),
                                "output_tokens": u.get("output_tokens", 0),
                            }
                        )
                        parsed = _parse_reply(resp.content, done)
                        return {i: parsed[i + 1] for i in done}, refine_usage, []
                    except Exception as exc:
                        if attempt == 1:
                            return {}, refine_usage, [
                                f"translator[{article['title'][:40]}]: refine batch of "
                                f"{len(done)} segment(s) failed ({exc}); keeping drafts"
                            ]
                return {}, refine_usage, []
            finally:
                if tracker:
                    tracker.add_done("translate", len(batch))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for batch_zh, batch_usage, batch_errors in pool.map(_refine_batch, all_batches):
                zh.update(batch_zh)
                usage.extend(batch_usage)
                errors.extend(batch_errors)

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
