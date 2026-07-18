"""Load the selected domains' glossaries, merged, into the branch state.

The user's domain selection order is the precedence order: when the same
EN key exists in two domains the earlier one wins. Phase 2 will surface
those collisions in the job summary; here the merge is silent.
"""

from src.agent.state import ArticleState
from src.tools.glossary_store import load_merged_glossary


def domain_glossary_loader(state: ArticleState) -> dict:
    return {"glossary": load_merged_glossary(state["domains"])}
