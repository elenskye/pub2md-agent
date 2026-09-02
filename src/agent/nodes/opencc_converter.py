"""Chinese-only path: convert Traditional/mixed script to Simplified.

No translation happens here — per the owner's rule the output for a Chinese
source article is a Simplified-Chinese-only Markdown file. Results are
shaped like translator output (translated_paragraphs + zh_title) so the
formatter and output_writer need no special casing beyond output_mode.

Graceful degradation: if conversion fails, the original text is kept and the
error is logged rather than losing the article.
"""

from src.agent.state import ArticleState
from src.tools.zh_script import simplifier


def opencc_converter(state: ArticleState) -> dict:
    article = state["article"]
    errors: list[str] = []

    def convert(text: str) -> str:
        return text

    if state.get("script_state") in ("traditional", "mixed"):
        convert, problem = simplifier()
        if problem:
            errors.append(f"opencc_converter[{article['title'][:40]}]: {problem}")

    flags = article.get("headings") or [False] * len(article["paragraphs"])
    pairs = [
        {"en": "", "zh": convert(p), "failed": False, "is_heading": heading}
        for p, heading in zip(article["paragraphs"], flags)
    ]
    return {
        "zh_title": convert(article["title"]),
        "zh_subtitle": convert(article["subtitle"]),
        "translated_paragraphs": pairs,
        "output_mode": "chinese_only",
        "errors": errors,
    }
