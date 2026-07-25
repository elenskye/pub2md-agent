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

A term belongs in the glossary ONLY if ALL THREE hold:
1. Different competent translators would plausibly render it differently —
   so consistency must be enforced. This covers terms of art, legal/act
   names, institutions, coined terms still settling, and proper nouns.
2. It is reusable across articles — not a one-off rhetorical phrase coined
   for a single story.
3. It does NOT already have one fixed, dictionary-standard Chinese
   rendering that every professional uses. Ordinary domain vocabulary
   (finance, politics, tech) with a settled rendering is the biggest
   source of glossary junk — be strict here.

Verdicts:
- "keep": belongs in the glossary as-is.
- "rewrite": contains a real term wrapped in rhetorical or descriptive
  words — give the minimal lexical unit in "term".
- "reject": everyday vocabulary or collocation that every translator
  renders the same way, standard domain vocabulary with one settled
  rendering, a one-off rhetorical phrase, or not a term at all.

Examples:
- "Posse Comitatus Act" → keep (act name, translation varies)
- "animal spirits" → keep (economics term of art)
- "Confederacy" → keep (proper noun with an established rendering)
- "agentic commerce" → keep (newly coined, renderings still diverging)
- "cradle of the Confederacy" → rewrite, term: "Confederacy" (rhetorical
  wrapper around the real term)
- "state failure" → reject (ordinary collocation, rendered identically by
  any translator)
- "crowd control" → reject (everyday vocabulary)
- "American carnage" → reject (one-off rhetorical phrase from a speech)
- "computer chip" → reject (everyday vocabulary)
- "Bird" / "Jump" → reject (single-word brand names that collide with a
  common English word: the glossary match is case-insensitive, so keeping
  them would corrupt ordinary uses of the word)
- "portfolio" → reject (standard finance vocabulary, always 投资组合)
- "cold war" → reject (historical event, one settled rendering)
- "listed company" → reject (settled: 上市公司 — criterion 3)
- "export controls" → reject (settled policy vocabulary)
- "incumbent" → reject (single common word, settled rendering)

Candidates:
{candidates}

Return ONLY a JSON object mapping every candidate exactly as written to
{{"verdict": "keep"|"rewrite"|"reject", "term": "<minimal form, required for rewrite>"{domain_field}}}.
"""

_DOMAIN_SECTION = """
This run reads several glossary domains at once: {domains}. Every kept or
rewritten term must be attributed to EXACTLY ONE of them — the field the
term belongs to, not the article's overall topic (a statistics term in a
public-administration paper still belongs to the quantitative domain that
owns it). Use only the listed domain slugs.
"""


def is_identity_mapping(en: str, zh: str) -> bool:
    """True when the resolved translation is just the English term again
    (case-insensitive). Such entries carry no information — the translator
    keeps unknown product/model names in English anyway — so they are
    filtered before reaching the glossary (owner decision, 2026-07-19,
    after "mlr3 => mlr3" landed)."""
    return en.strip().lower() == zh.strip().lower()


def judge_terms(
    terms: list[str], style: str, domains: list[str] | None = None
) -> tuple[dict, dict]:
    """Run the rubric over candidate terms. Returns (verdicts, token_usage);
    verdict entries carry "domain" when several domains are in play.
    Raises on LLM/parse failure — callers decide their fallback."""
    domains = domains or []
    attribute = len(domains) > 1
    llm = get_chat_model(
        max_tokens=1024, model_kwargs={"response_format": {"type": "json_object"}}
    )
    prompt = RUBRIC_PROMPT.format(
        style=style,
        candidates="\n".join(f"- {t}" for t in terms),
        domain_field=', "domain": "<one of: ' + ", ".join(domains) + '>"' if attribute else "",
    )
    if attribute:
        prompt += _DOMAIN_SECTION.format(domains=", ".join(domains))
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
            ruling = {
                "verdict": entry["verdict"],
                "term": str(entry.get("term", "")).strip(),
            }
            domain = str(entry.get("domain", "")).strip()
            if domain in domains:
                ruling["domain"] = domain
            verdicts[term.strip().lower()] = ruling
    return verdicts, usage


def apply_verdicts(
    candidates: list[str],
    verdicts: dict,
    article_text: str,
    glossary: dict,
    fallback_domain: str = "",
) -> tuple[list[str], list[str], dict[str, str]]:
    """Resolve verdicts into (accepted, rejected, term_domains). Rewrites
    must re-pass grounding (the minimal form must literally occur in the
    article) and glossary scoping; candidates the judge did not rule on are
    kept (fail open — the researcher can still resolve them). term_domains
    maps each accepted term to its attributed domain, defaulting to
    fallback_domain (the user's first-selected domain) when the judge gave
    none."""
    text_lower = article_text.lower()
    accepted: list[str] = []
    rejected: list[str] = []
    term_domains: dict[str, str] = {}
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
        term_domains[term] = (ruling or {}).get("domain") or fallback_domain
    return accepted, rejected, term_domains
