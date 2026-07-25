"""VLM layout hybrid: answer parsing, block boxes, ordered-page reflow."""

import pytest

from src.tools import vlm_layout
from src.tools.pdf_layout_parser import reflow
from src.tools.vlm_layout import _page_blocks, _parse_answer


def line(text, y0, x0, x1, block, page=0, size=10.0):
    return {
        "page": page, "x0": x0, "y0": y0, "x1": x1, "y1": y0 + 10,
        "text": text, "font_size": size, "block": block, "math_only": False,
    }


class TestParseAnswer:
    def test_valid_answer(self):
        order, roles = _parse_answer(
            '{"order": [2, 0, 1], "roles": {"0": "body", "1": "reference", "2": "title"}}',
            {0: 100, 1: 100, 2: 100},
        )
        assert order == [2, 0, 1]
        assert roles == {0: "body", 1: "reference", 2: "title"}

    def test_unknown_blocks_and_roles_ignored(self):
        order, roles = _parse_answer(
            '{"order": [0, 9, 1, 0], "roles": {"0": "poetry", "9": "body", "1": "body"}}',
            {0: 100, 1: 100},
        )
        assert order == [0, 1]  # 9 unknown, duplicate 0 removed
        assert roles == {1: "body"}

    def test_low_char_coverage_raises(self):
        with pytest.raises(ValueError):
            _parse_answer(
                '{"order": [0], "roles": {}}', {0: 10, 1: 500, 2: 500, 3: 500}
            )

    def test_omitted_tiny_blocks_still_pass(self):
        # The small VLM habitually skips tiny furniture blocks; substantive
        # coverage by characters must be enough.
        order, _ = _parse_answer(
            '{"order": [0, 1], "roles": {}}',
            {0: 900, 1: 900, 2: 10, 3: 10, 4: 10, 5: 10},
        )
        assert order == [0, 1]

    def test_role_labelled_blocks_count_as_accounted(self):
        # The model omits blocks from "order" once it labels them non-body;
        # such blocks are dropped anyway, so they satisfy coverage.
        order, roles = _parse_answer(
            '{"order": [0], "roles": {"1": "reference", "2": "caption"}}',
            {0: 500, 1: 800, 2: 700},
        )
        assert order == [0]
        assert roles == {1: "reference", 2: "caption"}


class TestPageBlocks:
    def test_boxes_span_all_block_lines(self):
        lines = [line("a", 100, 50, 200, block=0), line("b", 112, 55, 260, block=0),
                 line("c", 100, 300, 500, block=1)]
        boxes = _page_blocks(lines)
        assert boxes[0] == (50, 100, 260, 122)
        assert boxes[1] == (300, 100, 500, 110)


class TestOrderedPageReflow:
    def test_ordered_pages_preserve_given_sequence(self):
        # Right-column text deliberately FIRST in the list: an ordered page
        # must keep that sequence, while the geometric path would put the
        # left column first.
        lines = [
            line("Right column text comes first in reading order here.", 100, 300, 520, block=1),
            line("Left column text is read afterwards on this layout.", 400, 40, 260, block=0),
        ]
        ordered = reflow(lines, ordered_pages={0})
        assert [p["text"][:5] for p in ordered] == ["Right", "Left "]
        geometric = reflow(lines)
        assert geometric[0]["text"].startswith("Left")

    def test_mid_sentence_block_split_is_stitched(self):
        # A paragraph continuing across a column break ends mid-sentence in
        # its block; the continuation starts with a capitalised proper noun
        # and must still be joined on VLM-ordered pages.
        lines = [
            line("The project has been led by the founder of the Equal", 100, 40, 260, block=0),
            line("Justice Initiative, a non-profit law firm in Montgomery.", 100, 300, 520, block=1),
        ]
        out = reflow(lines, ordered_pages={0})
        assert len(out) == 1
        assert out[0]["text"].endswith("Montgomery.")
        assert "Equal Justice Initiative" in out[0]["text"]

    def test_disabled_without_vlm_env(self, monkeypatch):
        monkeypatch.delenv("VLM_MODEL", raising=False)
        monkeypatch.delenv("VLM_API_KEY", raising=False)
        assert not vlm_layout.enabled()
        out, pages, usage, errors = vlm_layout.resolve_reading_order([], "x.pdf")
        assert out == [] and pages == set() and usage == [] and errors == []
