"""Load the active style's glossary into the article branch state."""

from src.agent.state import ArticleState
from src.tools.glossary_store import load_glossary, terms_by_en


def style_glossary_loader(state: ArticleState) -> dict:
    doc = load_glossary(state["style"])
    return {"glossary": terms_by_en(doc)}
