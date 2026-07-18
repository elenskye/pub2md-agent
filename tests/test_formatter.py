"""Formatter output rules: currency escaping vs real math, inline-math
padding, and mode-specific layout."""

from src.agent.nodes.formatter import _escape_currency, _pad_inline_math, formatter


def _state(pairs, mode="bilingual", title="T", subtitle=""):
    return {
        "article": {"index": 0, "title": title, "subtitle": subtitle, "paragraphs": []},
        "base_style": "economist",
        "domains": ["econ"],
        "pdf_path": "/tmp/x.pdf",
        "output_mode": mode,
        "zh_title": "标题",
        "zh_subtitle": "",
        "translated_paragraphs": pairs,
    }


class TestEscapeCurrency:
    def test_currency_amounts_escaped(self):
        assert (
            _escape_currency("raised $86bn and later $60bn")
            == "raised \\$86bn and later \\$60bn"
        )

    def test_inline_math_untouched(self):
        assert _escape_currency("向量维度为 $d_{\\text{model}}$ 。") == "向量维度为 $d_{\\text{model}}$ 。"

    def test_display_math_untouched(self):
        assert _escape_currency("$$x = 1$$") == "$$x = 1$$"

    def test_fenced_placeholder_untouched(self):
        text = "```\n[formula] price $100\n```"
        assert _escape_currency(text) == text

    def test_padder_ignores_escaped_currency(self):
        # \$86bn ... \$60bn must not be treated as one inline-math span.
        text = _escape_currency("raised $86bn, sold for $60bn today")
        assert _pad_inline_math(text) == text


class TestFormatterIntegration:
    def test_bilingual_currency_and_math(self):
        pairs = [
            {
                "en": "SpaceX raised $86bn and bought Cursor for $60bn.",
                "zh": "SpaceX 筹资860亿美元。",
                "failed": False,
                "is_heading": False,
            },
            {
                "en": "The dimension is $d_k$.",
                "zh": "维度为 $d_k$ 。",
                "failed": False,
                "is_heading": False,
            },
        ]
        md = formatter(_state(pairs))["bilingual_md"]
        assert "raised \\$86bn" in md and "for \\$60bn" in md
        assert "$d_k$" in md  # real inline math survives unescaped

    def test_formula_block_passthrough(self):
        block = "$$\nx^2 + y^2 = 1\n$$"
        pairs = [{"en": block, "zh": block, "failed": False, "is_heading": False}]
        md = formatter(_state(pairs))["bilingual_md"]
        assert block in md
        # verbatim pair printed once, not twice
        assert md.count("x^2 + y^2 = 1") == 1

    def test_chinese_only_currency_escaped(self):
        pairs = [{"en": "", "zh": "估值 $4.4trn 创新高。", "failed": False, "is_heading": False}]
        md = formatter(_state(pairs, mode="chinese_only"))["bilingual_md"]
        assert "\\$4.4trn" in md
