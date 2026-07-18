"""Precision gate for term candidates (generate-critique split).

The extractor is recall-oriented; this node judges each candidate against
the shared rubric: keep real terms, rewrite rhetorical wrappers down to
their minimal lexical unit ("cradle of the Confederacy" → "Confederacy"),
reject everyday collocations ("state failure"). Only survivors reach the
Tavily researcher, so junk candidates no longer burn search calls.

Graceful degradation: if the judging call fails, the original candidates
pass through unchanged (previous behaviour) and the error is logged.
"""

from src.agent.state import ArticleState
from src.tools.term_rubric import apply_verdicts, judge_terms


def term_verifier(state: ArticleState) -> dict:
    candidates = state.get("term_candidates", [])
    if not candidates:
        return {}
    article = state["article"]
    full_text = "\n".join(
        [article["title"], article["subtitle"], *state.get("english_paragraphs", [])]
    )

    errors: list[str] = []
    usage: list[dict] = []
    try:
        verdicts, u = judge_terms(candidates, state["base_style"])
        usage.append({"node": "term_verifier", **u})
        accepted, rejected = apply_verdicts(
            candidates, verdicts, full_text, state.get("glossary", {})
        )
        if rejected:
            errors.append(
                f"term_verifier[{article['title'][:40]}]: rejected "
                f"{len(rejected)} candidate(s): {', '.join(rejected)}"
            )
        return {"term_candidates": accepted, "errors": errors, "token_usage": usage}
    except Exception as exc:
        errors.append(
            f"term_verifier[{article['title'][:40]}]: judging failed ({exc}); "
            "passing candidates through unverified"
        )
        return {"errors": errors}
