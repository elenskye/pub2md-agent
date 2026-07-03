"""Translate one article's paragraphs into Simplified Chinese.

Paragraphs are sent in numbered batches (cost control: bounded prompts,
bounded max_tokens) and the reply must echo every number back as JSON, which
guarantees EN/ZH alignment. Failure policy (spec 5.3): each batch gets up to
2 retries; paragraphs still failing are kept in English and marked
[translation failed] so the rest of the article survives.
"""

import json
from pathlib import Path

from src.agent.state import ArticleState
from src.config import get_chat_model

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


def _batches(items: list[str]) -> list[list[int]]:
    """Split segment indices into batches bounded by count and characters."""
    batches: list[list[int]] = [[]]
    chars = 0
    for i, text in enumerate(items):
        if batches[-1] and (len(batches[-1]) >= _BATCH_MAX_PARAS or chars + len(text) > _BATCH_MAX_CHARS):
            batches.append([])
            chars = 0
        batches[-1].append(i)
        chars += len(text)
    return batches


def _loads_with_repair(text: str) -> dict:
    """DeepSeek emits almost-JSON even in JSON mode: a value ending with a
    Chinese closing quote (”) deterministically loses its ASCII closing
    quote, and long replies can truncate mid-string. Try the raw text, then
    the known tail repairs — retrying the model does not help since the
    defect is reproducible byte-for-byte."""
    candidates = [text, text + '"}', text + "}"]
    stripped = text.rstrip()
    if stripped.endswith("}"):
        # Missing close-quote right before the final brace.
        candidates.append(stripped[:-1].rstrip() + '"}')
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            # strict=False tolerates literal newlines inside JSON strings.
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise last_error


def _parse_reply(content: str, expected: list[int]) -> dict[int, str]:
    text = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    raw = _loads_with_repair(text)
    out = {int(k): str(v).strip() for k, v in raw.items()}
    missing = [i for i in expected if i + 1 not in out or not out[i + 1]]
    if missing:
        raise ValueError(f"segments missing from reply: {[i + 1 for i in missing]}")
    return out


def translator(state: ArticleState) -> dict:
    article = state["article"]
    style = state["style"]
    # JSON mode: the API guarantees well-formed JSON, which plain prompting
    # does not (observed failures: bare newlines, missing closing quotes).
    llm = get_chat_model(model_kwargs={"response_format": {"type": "json_object"}})
    system = _load_style_prompt(style)

    # Title and standfirst are translated alongside the body in batch 1.
    segments = [article["title"]] + ([article["subtitle"]] if article["subtitle"] else [])
    n_meta = len(segments)
    segments += state.get("english_paragraphs", article["paragraphs"])

    zh: dict[int, str] = {}
    errors: list[str] = []
    usage: list[dict] = []

    for batch in _batches(segments):
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

    pairs = [
        {"en": segments[i], "zh": zh.get(i, FAILED_MARK), "failed": i not in zh}
        for i in range(n_meta, len(segments))
    ]
    return {
        "zh_title": zh.get(0, FAILED_MARK),
        "zh_subtitle": zh.get(1, FAILED_MARK) if article["subtitle"] else "",
        "translated_paragraphs": pairs,
        "output_mode": "bilingual",
        "errors": errors,
        "token_usage": usage,
    }
