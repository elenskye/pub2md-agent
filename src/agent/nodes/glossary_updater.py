"""Persist newly researched terms into the primary domain's glossary.

Writes go through glossary_store, whose transactions serialize parallel
article branches and let existing entries win over duplicates — that keeps
the glossary stable once a term is published. The branch state's in-memory
glossary is reloaded from disk afterwards so the translator sees exactly
what future runs will see.

Phase 1 interim rule: new terms land in the FIRST selected domain. Phase 2
replaces this with per-term domain attribution in the verifier rubric.
"""

from src.agent.state import ArticleState
from src.tools.glossary_store import add_terms, load_merged_glossary


def glossary_updater(state: ArticleState) -> dict:
    resolved = state.get("resolved_terms", [])
    if not resolved:
        return {}
    added = add_terms(state["domains"][0], resolved)
    return {
        "glossary": load_merged_glossary(state["domains"]),
        "new_terms": added,
        "resolved_terms": [],
    }
