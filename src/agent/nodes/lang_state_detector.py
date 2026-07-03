"""Detect each article's language state (rule-based, no LLM).

- has_english: Latin letters outnumber Han characters — then the article is
  translated from its English source.
- script_state: for Chinese text, round-trip OpenCC comparisons detect the
  script. t2s changing the text means traditional characters are present;
  s2t changing it means simplified-specific characters are present; both
  means mixed.
"""

from opencc import OpenCC

from src.agent.state import ArticleState
from src.tools.pdf_layout_parser import latin_han_counts

_t2s = OpenCC("t2s")
_s2t = OpenCC("s2t")

# Script detection needs only a sample, not a whole article.
_SAMPLE_CHARS = 4000


def lang_state_detector(state: ArticleState) -> dict:
    article = state["article"]
    text = " ".join([article["title"], article["subtitle"], *article["paragraphs"]])
    latin, han = latin_han_counts(text)
    has_english = latin > han

    if han == 0:
        script = "none"
    else:
        sample = text[:_SAMPLE_CHARS]
        has_traditional = _t2s.convert(sample) != sample
        has_simplified = _s2t.convert(sample) != sample
        if has_traditional and has_simplified:
            script = "mixed"
        elif has_traditional:
            script = "traditional"
        else:
            script = "simplified"

    return {"has_english": has_english, "script_state": script}
