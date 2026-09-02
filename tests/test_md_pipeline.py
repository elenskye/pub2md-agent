"""The .md path's read and write ends (no LLM involved)."""

from src.agent.nodes.md_reader import md_reader
from src.agent.nodes.md_writer import md_writer
from src.tools.md_fences import slots

_DOC = "# Handbook\n\nA sentence.\n\n## Setup\n\nAnother one.\n"


def _read(tmp_path, text=_DOC, name="input.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return md_reader({"md_path": str(path)}), str(path)


def test_reader_takes_the_title_from_the_first_heading(tmp_path):
    state, _ = _read(tmp_path)
    assert state["md_title"] == "Handbook"
    assert state["articles"][0]["title"] == "Handbook"
    assert len(slots(state["md_pieces"])) == 4


def test_reader_falls_back_to_the_filename_and_flags_empty_documents(tmp_path):
    state, _ = _read(tmp_path, text="```\nx = 1\n```\n", name="notes.md")
    assert state["md_title"] == "notes"
    assert state["errors"] and "no translatable text" in state["errors"][0]


def test_reader_prefers_the_uploaded_name_over_the_stored_one(tmp_path):
    """The web app writes every upload to input.md — the title must not
    become "input"."""
    path = tmp_path / "input.md"
    path.write_text("no heading here\n", encoding="utf-8")
    state = md_reader({"md_path": str(path), "md_source_name": "Field Notes.md"})
    assert state["md_title"] == "Field Notes"


def test_writer_footer_credits_the_uploaded_name_and_says_no_glossary(tmp_path):
    state, path = _read(tmp_path)
    md_writer(
        {
            **state,
            "md_path": path,
            "md_source_name": "Handbook.md",
            "md_translations": {},
            "base_style": "general",
            "domains": [],
            "output_dir": str(tmp_path / "out"),
        }
    )
    footer = (tmp_path / "out" / "Handbook-zh.md").read_text(encoding="utf-8")
    assert "Translated from `Handbook.md`" in footer
    assert "(general, no glossary)" in footer


def test_writer_names_by_title_not_by_upload_filename(tmp_path):
    """The web app stores every upload as input.md, so the source stem must
    not decide the output name."""
    state, path = _read(tmp_path)
    out = md_writer(
        {
            **state,
            "md_path": path,
            "md_translations": {s["id"]: "译文" for s in slots(state["md_pieces"])},
            "base_style": "academy",
            "domains": ["cs"],
            "output_dir": str(tmp_path / "out"),
        }
    )
    (result,) = out["results"]
    assert result["output_path"].endswith("Handbook-zh.md")
    assert result["mode"] == "markdown" and result["n_failed"] == 0

    written = (tmp_path / "out" / "Handbook-zh.md").read_text(encoding="utf-8")
    assert written.startswith("# 译文\n\n译文\n\n## 译文\n\n译文")
    assert "Machine translation" in written


def test_writer_keeps_the_source_text_for_untranslated_slots(tmp_path):
    state, path = _read(tmp_path)
    out = md_writer(
        {
            **state,
            "md_path": path,
            "md_translations": {0: "手册"},  # the rest failed
            "base_style": "academy",
            "domains": ["cs"],
            "output_dir": str(tmp_path / "out"),
        }
    )
    written = (tmp_path / "out" / "Handbook-zh.md").read_text(encoding="utf-8")
    assert "# 手册" in written and "A sentence." in written
    assert out["results"][0]["n_failed"] == 3
