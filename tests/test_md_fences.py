"""The .md path's structural fences: what the model may touch, and what the
program guarantees byte-for-byte."""

from pathlib import Path

import pytest

from src.tools.md_fences import (
    protect_inline,
    rebuild,
    restore_inline,
    segment,
    slot_mode,
    slots,
)


def _texts(md: str) -> list[str]:
    return [s["text"] for s in slots(segment(md))]


def _roundtrip(md: str) -> str:
    return rebuild(segment(md), {})


def _translate_all(md: str, zh: str = "译文") -> str:
    pieces = segment(md)
    return rebuild(pieces, {s["id"]: zh for s in slots(pieces)})


@pytest.mark.parametrize(
    "md",
    [
        "# Title\n\nA paragraph that\nwraps over lines.\n",
        "- item one\n  continued here\n- item two\n",
        "| A | B |\n|---|---|\n| one | two |\n",
        "```python\nx = 1  # a comment\n```\n",
        "```mermaid\nflowchart TD\n  A[Read the file] --> B[Write it]\n```\n",
        "```text\nsrc/          Agent core\n```\n",
        "> quoted line\n\n<!-- html comment -->\n",
        "---\ntitle: front matter\n---\n\n# Body\n",
    ],
)
def test_segmentation_is_lossless(md):
    """With no translations, rebuilding must return the exact input — the
    invariant the whole path rests on."""
    assert _roundtrip(md) == md


def test_real_readme_roundtrips():
    readme = Path(__file__).resolve().parents[1] / "README.md"
    source = readme.read_text(encoding="utf-8")
    assert _roundtrip(source) == source


def test_headings_and_paragraphs_are_slots_markers_are_not():
    pieces = segment("## Project structure\n\nSome prose here.\n")
    assert _texts("## Project structure\n\nSome prose here.\n") == [
        "Project structure",
        "Some prose here.",
    ]
    assert rebuild(pieces, {0: "项目结构", 1: "一些正文。"}) == "## 项目结构\n\n一些正文。\n"


def test_wrapped_list_item_is_one_slot():
    md = "- **Reads the page.** PyMuPDF gives lines with\n  coordinates and fonts.\n"
    assert _texts(md) == ["**Reads the page.** PyMuPDF gives lines with\n  coordinates and fonts."]


def test_table_cells_translate_but_pipes_and_separator_do_not():
    md = "| Variable | Effect |\n|---|---|\n| `LLM_PROVIDER` | translation model |\n"
    assert _texts(md) == ["Variable", "Effect", "translation model"]
    assert _translate_all(md) == "| 译文 | 译文 |\n|---|---|\n| `LLM_PROVIDER` | 译文 |\n"


def test_code_comments_translate_but_code_does_not():
    md = "```bash\ncp .env.example .env   # pick a provider block\nrm -rf x\n```\n"
    assert _texts(md) == ["pick a provider block"]
    assert "cp .env.example .env   # 译文" in _translate_all(md)


def test_comment_marker_inside_a_string_is_not_a_comment():
    md = '```python\nurl = "https://x/#frag"\n```\n'
    assert _texts(md) == []


def test_mermaid_labels_translate_but_arrows_and_ids_do_not():
    md = '```mermaid\nflowchart TD\n  A[Read file] -- "one per article" --> B[Write]\n```\n'
    assert _texts(md) == ["Read file", "one per article", "Write"]
    assert "A[译文] -- \"译文\" --> B[译文]" in _translate_all(md)


def test_plain_fence_translates_the_annotation_column_only():
    md = "```text\nsrc/agent/graph.py        Main graph assembly\npublic/\n```\n"
    assert _texts(md) == ["Main graph assembly"]
    assert "src/agent/graph.py        译文" in _translate_all(md)


def test_inline_code_urls_and_math_are_protected():
    md = "See `src/cli.py` and [the docs](https://x.dev) for $E=mc^2$ details.\n"
    (slot,) = slots(segment(md))
    assert slot["text"] == "See ⟦0⟧ and [the docs]⟦1⟧ for ⟦2⟧ details.\n".rstrip("\n")
    rebuilt = rebuild(
        segment(md), {0: "参见 ⟦0⟧ 与 [文档]⟦1⟧ 中关于 ⟦2⟧ 的说明。"}
    )
    assert rebuilt == "参见 `src/cli.py` 与 [文档](https://x.dev) 中关于 $E=mc^2$ 的说明。\n"


def test_dropped_placeholder_is_recovered_not_lost():
    """A model that swallows a placeholder must not silently delete a URL."""
    assert restore_inline("译文", ["`code`"]) == "译文 `code`"
    assert restore_inline("译文 ⟦9⟧", []) == "译文 "


def test_protect_inline_indexes_positionally():
    masked, spans = protect_inline("a `x` b `y`")
    assert masked == "a ⟦0⟧ b ⟦1⟧" and spans == ["`x`", "`y`"]


def test_chinese_slots_are_converted_not_translated():
    pieces = segment("# 繁體標題\n\nEnglish prose.\n")
    modes = {s["text"]: s["mode"] for s in slots(pieces)}
    assert modes["繁體標題"] == "opencc"
    assert modes["English prose."] == "translate"


def test_symbol_only_lines_never_become_slots():
    assert slot_mode("|---|") is None
    assert _texts("```\n---\n42\n```\n") == []


def test_front_matter_is_never_translated():
    md = "---\ntitle: Elen\ntags: [a, b]\n---\n\n# Heading\n"
    assert _texts(md) == ["Heading"]
