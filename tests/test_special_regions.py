"""Formula/table region masking (Phase 5)."""

from src.tools.pdf_layout_parser import mask_special_regions, reflow

PAGE = {"width": 612.0, "height": 792.0}


def line(text, y0, x0=108.0, x1=504.0, fs=10.0, math=False, page=0):
    return {
        "page": page,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y0 + fs,
        "text": text,
        "font_size": fs,
        "math_only": math,
    }


def prose(y0, text="Ordinary body prose that fills most of the column width."):
    return line(text, y0)


class TestFormulaMasking:
    def test_display_formula_masked_with_clip(self):
        lines = [
            prose(100),
            line("Attention(Q, K, V ) = softmax(QKT", y0=130, x0=220, x1=377, math=True),
            line("(1)", y0=131, x0=492, x1=504),  # equation number, text font
            prose(160),
        ]
        masked = mask_special_regions(lines, [PAGE])
        formulas = [ln for ln in masked if ln.get("special") == "formula"]
        assert len(formulas) == 1
        assert "(1)" in formulas[0]["text"] and formulas[0]["clip"][0] == 220

    def test_inline_math_prose_untouched(self):
        lines = [
            prose(100, "While for small values of dk the two mechanisms perform"),
            prose(112, "similarly, additive attention outperforms dot products."),
        ]
        masked = mask_special_regions(lines, [PAGE])
        assert masked == lines

    def test_formula_paragraph_survives_reflow_standalone(self):
        lines = [
            prose(100),
            line("FFN(x) = max(0, xW1 + b1)W2 + b2", y0=112, x0=200, x1=400, math=True),
            prose(124, "continuing prose right after the display equation here."),
        ]
        paras = reflow(mask_special_regions(lines, [PAGE]))
        specials = [p for p in paras if p.get("special") == "formula"]
        assert len(specials) == 1 and not specials[0]["is_heading"]


class TestTableMasking:
    def _table_rows(self, y0):
        rows = []
        for k in range(4):  # 4 rows × 4 fragments
            y = y0 + k * 12
            rows += [
                line("Self-Attention", y0=y, x0=125, x1=182),
                line("O(n2 · d)", y0=y, x0=264, x1=303),
                line("O(1)", y0=y, x0=351, x1=372),
                line("O(1)", y0=y, x0=431, x1=452),
            ]
        return rows

    def test_table_body_collapsed_to_placeholder(self):
        lines = [prose(80, "Table 1: Maximum path lengths for layer types."), *self._table_rows(117), prose(200)]
        masked = mask_special_regions(lines, [PAGE])
        placeholders = [ln for ln in masked if ln.get("special") == "table"]
        assert len(placeholders) == 1 and placeholders[0]["text"] == "[table omitted]"
        # caption survives
        assert any(ln["text"].startswith("Table 1:") for ln in masked)

    def test_wrapped_header_cell_swallowed(self):
        # A single-fragment row sandwiched between strong rows joins the table.
        rows = self._table_rows(117)
        rows.insert(4, line("Operations", y0=127, x0=339, x1=383))
        masked = mask_special_regions([*rows, prose(300)], [PAGE])
        assert not any(ln["text"] == "Operations" for ln in masked)

    def test_two_fragment_magazine_rows_not_tables(self):
        # EN + ZH columns give 2 fragments per row — must never trigger.
        lines = []
        for k in range(6):
            y = 100 + k * 30
            lines.append(line("English text on the left side of the page.", y0=y, x0=12, x1=416))
            lines.append(line("Chinese text on the right side.", y0=y, x0=427, x1=830))
        masked = mask_special_regions(lines, [PAGE])
        assert masked == lines
