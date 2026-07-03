"""Isolate the English source paragraphs of an article.

Any pre-existing Chinese translation is discarded here (spec 3.1: never
reused or graded — we always re-translate from the English source). For
majority-English documents most Chinese lines are already dropped at the
document level by noise_stripper; this per-article pass is the formal home
of that rule and catches residual mixed paragraphs.
"""

from src.agent.state import ArticleState
from src.tools.pdf_layout_parser import is_chinese_line


def en_text_isolator(state: ArticleState) -> dict:
    article = state["article"]
    english = [p for p in article["paragraphs"] if not is_chinese_line(p)]
    dropped = len(article["paragraphs"]) - len(english)
    errors = (
        [f"en_text_isolator[{article['title'][:40]}]: dropped {dropped} residual Chinese paragraph(s)"]
        if dropped
        else []
    )
    return {"english_paragraphs": english, "errors": errors}
