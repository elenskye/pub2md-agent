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
    flags = article.get("headings") or [False] * len(article["paragraphs"])
    kept = [
        (text, heading)
        for text, heading in zip(article["paragraphs"], flags)
        if not is_chinese_line(text)
    ]
    dropped = len(article["paragraphs"]) - len(kept)
    errors = (
        [f"en_text_isolator[{article['title'][:40]}]: dropped {dropped} residual Chinese paragraph(s)"]
        if dropped
        else []
    )
    return {
        "english_paragraphs": [text for text, _ in kept],
        "english_headings": [heading for _, heading in kept],
        "errors": errors,
    }
