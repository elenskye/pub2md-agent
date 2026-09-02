"""Translate the slots of a Markdown document into Simplified Chinese.

Output is Chinese-only (owner's rule for this path): each slot is replaced,
not duplicated. Two kinds of slot are handled differently — English prose
goes to the LLM under the same base-style prompt and glossary constraints as
the PDF path, while a slot that already contains Han characters is converted
Traditional→Simplified locally, so Chinese is never "translated" twice and
costs nothing.

Terminology is read-only here: known glossary terms are enforced, but no new
term is researched or written (owner's decision — a direct translation must
be fast and must not grow the glossary unaudited).

The model only ever sees plain strings with ⟦n⟧ placeholders; every fence,
pipe, bullet and URL is restored by the program afterwards.
"""

import os
from concurrent.futures import ThreadPoolExecutor

from src.agent.state import PipelineState
from src.config import get_chat_model
from src.tools.md_fences import slots
from src.tools.progress import tracker_from
from src.tools.translate_common import (
    batches,
    glossary_constraints,
    glossary_hits,
    load_style_prompt,
    parse_reply,
)
from src.tools.zh_script import simplifier

_MAX_ATTEMPTS = 3  # 1 try + 2 retries

_FENCE_RULES = """\
These segments come from a Markdown file whose structure is handled by the
program, not by you. Therefore:
- Translate the text only. Never add, remove or repair Markdown syntax
  (no #, -, |, backticks, brackets) that is not already inside a segment.
- Keep every ⟦n⟧ placeholder exactly as it appears: same digits, same
  order. They stand for code, links, math and HTML that must not change.
- Keep proper nouns, file paths, commands and identifiers in their original
  form; translate the prose around them.
- A segment may be a heading, a table cell, a code comment or a tree label:
  translate it as the short label it is, without inventing extra words.
"""

_USER_TEMPLATE = """\
Translate each numbered segment below into Simplified Chinese.
Return ONLY a JSON object mapping every segment number to its translation,
e.g. {{"1": "...", "2": "..."}}. Do not merge, split, skip or add segments.

{segments}
"""

_REFINE_TEMPLATE = """\
Below are numbered English segments with their draft Simplified-Chinese
translations. Review every draft against its English source and the style
rules from the system prompt: fix mistranslations, enforce the glossary, and
polish the wording. Keep every ⟦n⟧ placeholder intact. Return ONLY a JSON
object mapping every segment number to the final translation.

{pairs}
"""


def md_translator(state: PipelineState, config=None) -> dict:
    pieces = state.get("md_pieces", [])
    tracker = tracker_from(config)
    entries = slots(pieces)
    errors: list[str] = []
    usage: list[dict] = []
    zh: dict[int, str] = {}

    convert, problem = simplifier()
    if problem and any(e["mode"] == "opencc" for e in entries):
        errors.append(f"md_translator: {problem}")
    for entry in entries:
        if entry["mode"] == "opencc":
            zh[entry["id"]] = convert(entry["text"])

    texts = [e["text"] for e in entries]
    translatable = [i for i, e in enumerate(entries) if e["mode"] == "translate"]
    if not translatable:
        return {"md_translations": zh, "errors": errors, "token_usage": usage}

    hits = glossary_hits(state.get("glossary", {}), "\n".join(texts))
    system = load_style_prompt(state["base_style"]) + glossary_constraints(hits) + "\n\n" + _FENCE_RULES
    llm = get_chat_model(model_kwargs={"response_format": {"type": "json_object"}})

    def _call(prompt: str, expected: list[int], node: str, attempts: int) -> tuple[dict, list, str]:
        call_usage: list[dict] = []
        for attempt in range(attempts):
            try:
                resp = llm.invoke([("system", system), ("user", prompt)])
                u = resp.usage_metadata or {}
                call_usage.append(
                    {
                        "node": node,
                        "input_tokens": u.get("input_tokens", 0),
                        "output_tokens": u.get("output_tokens", 0),
                    }
                )
                return parse_reply(resp.content, expected), call_usage, ""
            except Exception as exc:  # noqa: BLE001 — degrade per batch
                if attempt == attempts - 1:
                    return {}, call_usage, str(exc)
        return {}, call_usage, ""

    def _translate(batch: list[int]) -> tuple[dict[int, str], list[dict], list[str]]:
        try:
            numbered = "\n\n".join(f"[{i + 1}] {texts[i]}" for i in batch)
            parsed, batch_usage, failure = _call(
                _USER_TEMPLATE.format(segments=numbered), batch, "md_translator", _MAX_ATTEMPTS
            )
            if failure:
                # Fail-open: untranslated slots keep their English source, so
                # a bad batch costs fidelity, never the document.
                return {}, batch_usage, [
                    f"md_translator: batch of {len(batch)} segment(s) failed after "
                    f"{_MAX_ATTEMPTS} attempts: {failure}"
                ]
            return {entries[i]["id"]: parsed[i + 1] for i in batch}, batch_usage, []
        finally:
            if tracker:
                tracker.add_done("translate", len(batch))

    all_batches = batches(texts, translatable)
    refine = bool(state.get("refine"))
    if tracker:
        tracker.add_total("translate", len(translatable) * (2 if refine else 1))
    workers = max(1, int(os.getenv("TRANSLATE_CONCURRENCY", "4")))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for batch_zh, batch_usage, batch_errors in pool.map(_translate, all_batches):
            zh.update(batch_zh)
            usage.extend(batch_usage)
            errors.extend(batch_errors)

    if refine:

        def _refine(batch: list[int]) -> tuple[dict[int, str], list[dict], list[str]]:
            try:
                done = [i for i in batch if entries[i]["id"] in zh]
                if not done:
                    return {}, [], []
                pairs = "\n\n".join(
                    f"[{i + 1}] EN: {texts[i]}\nZH: {zh[entries[i]['id']]}" for i in done
                )
                parsed, refine_usage, failure = _call(
                    _REFINE_TEMPLATE.format(pairs=pairs), done, "md_translator_refine", 2
                )
                if failure:
                    return {}, refine_usage, [
                        f"md_translator: refine batch of {len(done)} segment(s) failed "
                        f"({failure}); keeping drafts"
                    ]
                return {entries[i]["id"]: parsed[i + 1] for i in done}, refine_usage, []
            finally:
                if tracker:
                    tracker.add_done("translate", len(batch))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for batch_zh, batch_usage, batch_errors in pool.map(_refine, all_batches):
                zh.update(batch_zh)
                usage.extend(batch_usage)
                errors.extend(batch_errors)

    return {"md_translations": zh, "errors": errors, "token_usage": usage}
