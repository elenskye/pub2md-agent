"""Chinese-only path: convert Traditional/mixed script to Simplified.

No translation happens here — per the owner's rule the output for a Chinese
source article is a Simplified-Chinese-only Markdown file. Results are
shaped like translator output (translated_paragraphs + zh_title) so the
formatter and output_writer need no special casing beyond output_mode.

Graceful degradation: if conversion fails, the original text is kept and the
error is logged rather than losing the article.
"""

from src.agent.state import ArticleState

# OpenCC converts characters/phrases, not punctuation.
_PUNCT_MAP = str.maketrans({"「": "“", "」": "”", "『": "‘", "』": "’"})


def opencc_converter(state: ArticleState) -> dict:
    article = state["article"]
    errors: list[str] = []

    def convert(text: str) -> str:
        return text

    if state.get("script_state") in ("traditional", "mixed"):
        try:
            from opencc import OpenCC

            # tw2sp > t2s: handles 著→着 correctly and converts Taiwan
            # vocabulary to mainland usage (資訊→信息).
            cc = OpenCC("tw2sp")
            convert = lambda text: cc.convert(text).translate(_PUNCT_MAP)  # noqa: E731
        except Exception as exc:
            errors.append(
                f"opencc_converter[{article['title'][:40]}]: conversion unavailable "
                f"({exc}); keeping original script"
            )

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
