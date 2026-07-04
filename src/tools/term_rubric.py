"""Shared rubric for judging glossary-term candidates.

Used in two places with identical criteria: the term_verifier node (gating
new candidates during a run) and scripts/audit_glossary.py (retro-auditing
entries already in the glossary). The few-shot counterexamples are real
failures observed in this project's own glossary.
"""

from src.config import get_chat_model
from src.tools.llm_json import loads_with_repair, strip_fences

RUBRIC_PROMPT = """\
You curate a terminology glossary used to keep translations consistent
across many {style}-style articles. Judge each candidate term below.

A term belongs in the glossary ONLY if BOTH hold:
1. Different competent translators would plausibly render it differently —
   so consistency must be enforced. This covers terms of art, legal/act
   names, institutions, and proper nouns with established Chinese names.
2. It is reusable across articles — not a one-off rhetorical phrase coined
   for a single story.

Verdicts:
- "keep": belongs in the glossary as-is.
- "rewrite": contains a real term wrapped in rhetorical or descriptive
  words — give the minimal lexical unit in "term".
- "reject": everyday vocabulary or collocation that every translator
  renders the same way, a one-off rhetorical phrase, or not a term at all.

Examples:
- "Posse Comitatus Act" → keep (act name, translation varies)
- "animal spirits" → keep (economics term of art)
- "Confederacy" → keep (proper noun with an established rendering)
- "cradle of the Confederacy" → rewrite, term: "Confederacy" (rhetorical
  wrapper around the real term)
- "state failure" → reject (ordinary collocation, rendered identically by
  any translator)
- "crowd control" → reject (everyday vocabulary)
- "American carnage" → reject (one-off rhetorical phrase from a speech)
- "computer chip" → reject (everyday vocabulary)

Candidates:
{candidates}

Return ONLY a JSON object mapping every candidate exactly as written to
{{"verdict": "keep"|"rewrite"|"reject", "term": "<minimal form, required for rewrite>"}}.
"""


def judge_terms(terms: list[str], style: str) -> tuple[dict, dict]:
    """Run the rubric over candidate terms. Returns (verdicts, token_usage).
    Raises on LLM/parse failure — callers decide their fallback."""
    llm = get_chat_model(
        max_tokens=1024, model_kwargs={"response_format": {"type": "json_object"}}
    )
    prompt = RUBRIC_PROMPT.format(style=style, candidates="\n".join(f"- {t}" for t in terms))
    resp = llm.invoke(prompt)
    u = resp.usage_metadata or {}
    usage = {
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
    }
    raw = loads_with_repair(strip_fences(resp.content))
    verdicts = {}
    for term, entry in raw.items():
        if isinstance(entry, dict) and entry.get("verdict") in ("keep", "rewrite", "reject"):
            verdicts[term.strip().lower()] = {
                "verdict": entry["verdict"],
                "term": str(entry.get("term", "")).strip(),
            }
    return verdicts, usage


def apply_verdicts(
    candidates: list[str], verdicts: dict, article_text: str, glossary: dict
) -> tuple[list[str], list[str]]:
    """Resolve verdicts into (accepted, rejected) candidate lists. Rewrites
    must re-pass grounding (the minimal form must literally occur in the
    article) and glossary scoping; candidates the judge did not rule on are
    kept (fail open — the researcher can still resolve them)."""
    text_lower = article_text.lower()
    accepted: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        ruling = verdicts.get(cand.lower())
        term = cand
        if ruling:
            if ruling["verdict"] == "reject":
                rejected.append(cand)
                continue
            if ruling["verdict"] == "rewrite":
                minimal = ruling["term"]
                if not minimal or minimal.lower() not in text_lower:
                    rejected.append(cand)
                    continue
                term = minimal
        key = term.lower()
        if key in seen or key in glossary:
            continue
        seen.add(key)
        accepted.append(term)
    return accepted, rejected
