"""Persist newly researched terms into the style's glossary file.

Writes go through glossary_store, which locks the file (parallel article
branches) and lets existing entries win over duplicates — that keeps the
glossary stable once a term is published. The branch state's in-memory
glossary is reloaded from disk afterwards so the translator sees exactly
what future runs will see.
"""

from src.agent.state import ArticleState
from src.tools.glossary_store import add_terms, load_glossary, terms_by_en


def glossary_updater(state: ArticleState) -> dict:
    resolved = state.get("resolved_terms", [])
    if not resolved:
        return {}
    added = add_terms(state["style"], resolved)
    return {
        "glossary": terms_by_en(load_glossary(state["style"])),
        "new_terms": added,
        "resolved_terms": [],
    }
