"""Unit tests for the pure layout logic in pdf_layout_parser.

Line fixtures replicate the geometry patterns of the real test PDFs:
justified magazine text (uniform gaps, paragraph = larger gap), Chinese
justified text (uniform gaps, paragraph = short previous line), and
ragged-right news text (noisy right edge)."""

from src.tools.pdf_layout_parser import (
    cjk_ratio,
    drop_embedded_translation,
    is_chinese_line,
    is_header_furniture,
    is_non_prose,
    is_page_number,
    latin_han_counts,
    reflow,
    strip_noise,
)


def line(text, page=0, x0=10.0, y0=0.0, x1=400.0, y1=None, fs=12.0):
    return {
        "page": page,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1 if y1 is not None else y0 + fs,
        "text": text,
        "font_size": fs,
    }


PAGE = {"width": 842.0, "height": 595.0}


class TestNoisePredicates:
    def test_page_number_in_bottom_strip(self):
        assert is_page_number(line("12", y0=540), PAGE)

    def test_digits_in_body_are_not_page_numbers(self):
        assert not is_page_number(line("2026", y0=100), PAGE)

    def test_masthead_date(self):
        assert is_header_furniture(line("2026.7.2", y0=40, y1=60), PAGE)

    def test_chinese_line_detection(self):
        assert is_chinese_line("美国工业并非崩溃")
        # Latin brand names dilute the ratio but Han chars still mark it.
        assert is_chinese_line("他是Bending Spoons的老板兼联合创始人 Corriere della Sera")
        assert not is_chinese_line("A plain English sentence.")

    def test_latin_han_counts(self):
        latin, han = latin_han_counts("GDP占比24%，持续成长")
        assert latin == 3 and han == 6  # ，是标点，不计入汉字

    def test_cjk_ratio_counts_fullwidth_punct(self):
        assert cjk_ratio("（引号）") == 1.0


class TestNonProse:
    def test_equation_number(self):
        assert is_non_prose("(3)")

    def test_index_debris(self):
        assert is_non_prose("i i i")

    def test_math_fragment(self):
        assert is_non_prose("and W O ∈Rhdv×dmodel.")

    def test_two_word_crosshead_is_prose(self):
        assert not is_non_prose("Carnage v comeback")

    def test_chinese_is_always_prose(self):
        assert not is_non_prose("美国制造业只是转移")

    def test_normal_sentence(self):
        assert not is_non_prose("The invention of the cotton gin changed everything.")


class TestStripNoise:
    def test_running_header_keeps_largest_font_occurrence(self):
        lines = [
            line("The Myth of Deindustrialization", page=0, y0=70, fs=30.0),
            line("正文第一段的内容在这里，长度足够充当正文使用。", page=0, y0=200),
            line("The Myth of Deindustrialization", page=1, y0=20, fs=12.0),
            line("正文第二段的内容在这里，长度也足够充当正文使用。", page=1, y0=200),
        ]
        kept = strip_noise(lines, [PAGE, PAGE])
        titles = [ln for ln in kept if ln["text"].startswith("The Myth")]
        assert len(titles) == 1 and titles[0]["font_size"] == 30.0

    def test_note_app_ui_labels_and_row_partners_dropped(self):
        lines = [
            line("Status", page=0, x0=95, y0=235),
            line("Final", page=0, x0=170, y0=235),
            line("A real paragraph of body text that should stay.", page=0, y0=300),
        ]
        kept = strip_noise(lines, [PAGE])
        assert [ln["text"] for ln in kept] == ["A real paragraph of body text that should stay."]

    def test_tiny_font_print_artifacts_dropped(self):
        lines = [
            line("Body text at normal size that represents the article.", y0=100, fs=12.0),
            line("file:///Users/x/article.pdf — printed footer", y0=560, fs=7.5),
            line("More body text at normal size to weight the median.", y0=130, fs=12.0),
        ]
        kept = strip_noise(lines, [PAGE])
        assert all(ln["font_size"] == 12.0 for ln in kept)


class TestEmbeddedTranslation:
    def test_dropped_when_english_majority(self):
        lines = [
            line("An English source paragraph with plenty of words in it."),
            line("这是嵌入的中文翻译行，应当被丢弃。"),
        ]
        kept = drop_embedded_translation(lines)
        assert len(kept) == 1 and kept[0]["text"].startswith("An English")

    def test_kept_when_chinese_majority(self):
        lines = [
            line("这是中文来源文档的正文段落，占据文档的绝大多数篇幅内容。"),
            line("短英文行 GDP"),
        ]
        assert drop_embedded_translation(lines) == lines


class TestReflow:
    def test_paragraphs_split_by_vertical_gap(self):
        # Magazine pattern: 30pt line spacing, 60pt paragraph gap.
        lines = [
            line("First paragraph starts here and", y0=0, fs=14),
            line("continues on the second line.", y0=30, fs=14),
            line("Second paragraph starts after a gap and", y0=90, fs=14),
            line("also continues on a second line.", y0=120, fs=14),
        ]
        paras = reflow(lines)
        assert [p["text"][:5] for p in paras] == ["First", "Secon"]

    def test_cjk_lines_join_without_space(self):
        lines = [
            line("主流观点普遍认为，美国制造业日渐萎缩且竞争力不及中国，因此经历", y0=0, x1=516),
            line("了大规模的去工业化。", y0=24, x1=200),
        ]
        paras = reflow(lines)
        assert "经历了大规模" in paras[0]["text"]

    def test_dehyphenation(self):
        lines = [
            line("The committee discussed macro-", y0=0, x1=400),
            line("economics for three hours.", y0=24, x1=380),
        ]
        assert "macroeconomics" in reflow(lines)[0]["text"]

    def test_short_previous_line_starts_new_paragraph(self):
        # Chinese pattern: uniform gaps, paragraph signalled by short line.
        # Enough full-width lines that the typical right-edge deficit is 0.
        lines = [
            line("第一段的第一行内容文字填充到接近右边界的位置全部占满了", y0=0, x1=516),
            line("第一段的第二行内容文字也同样填充到接近右边界全部占满", y0=24, x1=516),
            line("第一段的第三行内容继续填充到接近右侧边界占满整行文字", y0=48, x1=516),
            line("第一段的最后一行提前结束。", y0=72, x1=200),
            line("第二段的第一行内容文字同样填充到接近右边界占满整行了", y0=96, x1=516),
            line("第二段继续的内容。", y0=120, x1=180),
        ]
        paras = reflow(lines)
        assert len(paras) == 2

    def test_same_row_font_fragments_stay_joined(self):
        # PyMuPDF splits one visual row at font changes (italic names);
        # the short-line rule must not fire without a row advance.
        lines = [
            line("according to research published by David Autor, David", y0=0, x1=300, fs=14),
            line("Dorn", y0=0, x0=305, x1=340, fs=14),
            line("and Gordon Hanson. However painful for those people,", y0=30, x1=416, fs=14),
            line("that did not rattle the broader job market very much at all.", y0=60, x1=410, fs=14),
        ]
        paras = reflow(lines)
        assert len(paras) == 1 and "David Dorn and Gordon" in paras[0]["text"]

    def test_cross_page_continuation_merges(self):
        lines = [
            line(
                "The first part of the sentence continues right across the page",
                page=0,
                y0=500,
                x1=416,
            ),
            line("boundary and finishes here.", page=1, y0=30, x1=300),
        ]
        paras = reflow(lines)
        assert len(paras) == 1

    def test_heading_marked_and_bounds_article(self):
        lines = [
            line("A Large Font Headline", y0=0, fs=20),
            line("Body text follows the headline and is much longer, spanning", y0=40, fs=12),
            line("multiple lines of ordinary paragraph content in the column.", y0=64, fs=12),
        ]
        paras = reflow(lines)
        assert paras[0]["is_heading"] and paras[0]["font_heading"]
        assert not paras[1]["is_heading"]

    def test_body_font_crosshead_is_heading_but_not_font_heading(self):
        lines = [
            line("The previous paragraph of the article runs a full line and", y0=0, fs=12, x1=516),
            line("then ends with a period.", y0=24, fs=12, x1=250),
            line("Carnage v comeback", y0=72, fs=12, x1=150),
            line("The next paragraph resumes ordinary body text right after", y0=120, fs=12, x1=516),
            line("the crosshead and keeps going for a while longer here too", y0=144, fs=12, x1=516),
            line("before it also finally ends.", y0=168, fs=12, x1=280),
        ]
        paras = reflow(lines)
        cross = [p for p in paras if p["text"] == "Carnage v comeback"]
        assert cross and cross[0]["is_heading"] and not cross[0]["font_heading"]

    def test_split_callout_demoted_and_merged(self):
        # 繁体 💡 card: oversized first line ends mid-clause, continuation
        # in body font.
        lines = [
            line("💡在高度分工的现代经济下，「把制造业带回美国」是假议题；一", y0=0, fs=18, x1=505),
            line("味追求复兴劳动密集的制造业，只会让美国得不偿失。", y0=30, fs=12, x1=499),
            line("主流观点普遍认为，美国制造业日渐萎缩且竞争力不及中国，如此", y0=90, fs=12, x1=516),
            line("经历了大规模的去工业化，论述引发了广泛的辩论。", y0=114, x1=400, fs=12),
        ]
        paras = reflow(lines)
        callout = paras[0]
        assert "一味追求" in callout["text"]
        assert not callout["is_heading"]

    def test_comma_title_survives_demotion(self):
        # NYT-style title contains a comma but the next paragraph starts a
        # fresh sentence — must stay a heading.
        lines = [
            line("Use of Troops Was Unlawful, Judge Rules", y0=0, fs=30, x1=500),
            line("A federal judge ruled on Tuesday that the administration had", y0=60, fs=12, x1=516),
            line("violated a nineteenth century law with the deployment.", y0=84, fs=12, x1=450),
        ]
        paras = reflow(lines)
        assert paras[0]["is_heading"] and paras[0]["font_heading"]
