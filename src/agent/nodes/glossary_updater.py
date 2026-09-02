"""Persist newly researched terms into their attributed domains' glossaries.

Each resolved term carries the domain the verifier attributed it to
(strictly one domain per term — v3 rule); writes go through glossary_store,
whose transactions serialize parallel article branches and let existing
entries win over duplicates. The branch state's in-memory glossary is
reloaded from disk afterwards so the translator sees exactly what future
runs will see.

Every actually-added term also gets a term_occurrences row with a real
example sentence from this article (wordbook raw material).

Runtime writes land as CANDIDATES (v3 Phase 5): immediately usable by this
and later runs, but authoritative only after the owner's rubric+human audit
promotes them and a regenerated seed JSON ships them.
"""

from src.agent.state import ArticleState
from src.tools.glossary_store import add_terms, load_merged_glossary, record_occurrences
from src.tools.term_context import extract_example


def glossary_updater(state: ArticleState) -> dict:
    resolved = state.get("resolved_terms", [])
    if not resolved:
        return {}
    fallback = state["domains"][0]
    added: list[dict] = []
    for term in resolved:
        domain = term.get("domain") or fallback
        for entry in add_terms(domain, [term]):
            added.append({**entry, "domain": domain})

    article = state["article"]
    paragraphs = [article["title"], article["subtitle"], *state.get("english_paragraphs", [])]
    record_occurrences(
        [
            {
                "domain": t["domain"],
                "en": t["en"],
                "article_title": article["title"],
                "sentence": extract_example(t["en"], paragraphs),
            }
            for t in added
        ]
    )
    return {
        "glossary": load_merged_glossary(state["domains"]),
        "new_terms": added,
        "resolved_terms": [],
    }
