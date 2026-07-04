"""Metrics for the agent-vs-baseline evaluation (spec section 7).

1. Multi-article split accuracy — files produced vs the hand-labelled count.
2. Terminology metrics (headline):
   - glossary adherence: of all glossary-term occurrences in English source
     paragraphs, how many translations use the glossary rendering;
   - cross-article consistency: of glossary terms occurring 2+ times across
     the corpus, how many are rendered identically (i.e. adherent) everywhere.
3. LLM-as-judge accuracy/fluency scores (1-5) on sampled pairs.
4. Paragraph-boundary accuracy vs a hand-checked reference file
   (eval/references/<pdf-stem>.txt, one English paragraph per line) — skipped
   for items that have no reference yet.
"""

import re
from pathlib import Path

from src.config import get_chat_model
from src.tools.llm_json import loads_with_repair, strip_fences

_JUDGE_PROMPT = """\
You are grading an English→Simplified-Chinese translation.

English source:
{en}

Chinese translation:
{zh}

Score 1-5 (5 best): "accuracy" (meaning preserved, nothing added/omitted)
and "fluency" (natural written Chinese). Return ONLY a JSON object:
{{"accuracy": <int>, "fluency": <int>}}.
"""


def _zh_variants(zh: str) -> list[str]:
    """Acceptable renderings of a glossary translation inside a paragraph:
    the full form, the part before a parenthetical gloss, and the form
    without 《》 quoting."""
    variants = {zh, zh.split("（")[0], zh.replace("《", "").replace("》", "")}
    return [v.strip() for v in variants if len(v.strip()) >= 2]


def term_occurrences(pairs: list[dict], glossary: dict) -> list[dict]:
    """Every (glossary term, paragraph) occurrence with its adherence flag.
    Word-boundary matching keeps 'ICE' from matching 'justice'."""
    occurrences = []
    for pair in pairs:
        if pair.get("failed") or not pair.get("en"):
            continue
        en_lower = pair["en"].lower()
        for key, term in glossary.items():
            if not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", en_lower):
                continue
            hit = any(v in pair["zh"] for v in _zh_variants(term["zh"]))
            occurrences.append({"term": key, "zh": term["zh"], "hit": hit})
    return occurrences


def adherence_rate(occurrences: list[dict]) -> tuple[float, int]:
    if not occurrences:
        return 1.0, 0
    hits = sum(1 for o in occurrences if o["hit"])
    return hits / len(occurrences), len(occurrences)


def consistency_rate(occurrences: list[dict]) -> tuple[float, int]:
    """Spec's headline metric over terms occurring 2+ times in the corpus."""
    by_term: dict[str, list[bool]] = {}
    for o in occurrences:
        by_term.setdefault(o["term"], []).append(o["hit"])
    multi = {t: hits for t, hits in by_term.items() if len(hits) >= 2}
    if not multi:
        return 1.0, 0
    consistent = sum(1 for hits in multi.values() if all(hits))
    return consistent / len(multi), len(multi)


def judge_pairs(pairs: list[dict], max_samples: int = 6) -> dict:
    """LLM-as-judge on evenly sampled paragraph pairs."""
    scorable = [p for p in pairs if p.get("en") and not p.get("failed")]
    if not scorable:
        return {"accuracy": None, "fluency": None, "n": 0}
    step = max(1, len(scorable) // max_samples)
    sample = scorable[::step][:max_samples]
    llm = get_chat_model(
        max_tokens=64, model_kwargs={"response_format": {"type": "json_object"}}
    )
    scores = []
    for pair in sample:
        try:
            resp = llm.invoke(_JUDGE_PROMPT.format(en=pair["en"][:1500], zh=pair["zh"][:1500]))
            raw = loads_with_repair(strip_fences(resp.content))
            scores.append((int(raw["accuracy"]), int(raw["fluency"])))
        except Exception:
            continue
    if not scores:
        return {"accuracy": None, "fluency": None, "n": 0}
    return {
        "accuracy": round(sum(s[0] for s in scores) / len(scores), 2),
        "fluency": round(sum(s[1] for s in scores) / len(scores), 2),
        "n": len(scores),
    }


def paragraph_boundary_f1(agent_paragraphs: list[str], pdf_path: str) -> float | None:
    """Exact-match F1 against a hand-checked reference; None if no reference."""
    ref_path = Path("eval/references") / f"{Path(pdf_path).stem}.txt"
    if not ref_path.exists():
        return None
    reference = [ln.strip() for ln in ref_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not reference:
        return None
    produced = [p.strip() for p in agent_paragraphs if p.strip()]
    matches = len(set(produced) & set(reference))
    precision = matches / len(produced) if produced else 0.0
    recall = matches / len(reference)
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 3)
