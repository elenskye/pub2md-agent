"""Deterministic non-body filters + gatekeeper keep/drop logic (Phase 3)."""

from src.agent.nodes import body_gatekeeper as bg
from src.tools.body_filters import (
    cut_references,
    deterministic_filter,
    is_caption,
    is_killed,
)


class TestKillList:
    def test_email_line_killed(self):
        assert is_killed("Email: florian.pargent@psy.lmu.de")

    def test_doi_line_killed(self):
        assert is_killed("https://doi.org/10.1177/25152459231162559")

    def test_license_block_killed(self):
        assert is_killed(
            "Creative Commons NonCommercial CC BY-NC: This article is "
            "distributed under the terms of the Creative Commons "
            "Attribution-NonCommercial 4.0 License"
        )

    def test_correspondence_killed(self):
        assert is_killed("Corresponding author: Florian Pargent, Department of Psychology")

    def test_body_prose_about_copyright_survives(self):
        assert not is_killed("The ruling reshaped how copyright law treats AI training data.")

    def test_plain_prose_survives(self):
        assert not is_killed("Supervised machine learning has become a central tool.")


class TestCaption:
    def test_figure_and_table_openers(self):
        assert is_caption("Figure 3: Cross-validation error by model class.")
        assert is_caption("Table 2. Hyperparameter search spaces.")
        assert is_caption("Fig. 1: Overview of the pipeline.")

    def test_prose_mentioning_figure_survives(self):
        assert not is_caption("As Figure 3 shows, the error decreases with more folds.")


class TestReferencesCut:
    def test_everything_after_references_heading_dropped(self):
        paras = ["Body one.", "References", "Pargent, F. (2023). Best practices.", "More refs."]
        headings = [False, True, False, False]
        kept_p, kept_h, n = cut_references(paras, headings)
        assert kept_p == ["Body one."] and kept_h == [False] and n == 3

    def test_no_references_heading_keeps_all(self):
        paras = ["Body one.", "Body two."]
        kept_p, _, n = cut_references(paras, [False, False])
        assert kept_p == paras and n == 0


class TestDeterministicFilter:
    def test_headings_and_formulas_never_filtered(self):
        paras = ["Figure 1: not really a heading", "$$x^2$$", "Email: a@b.com"]
        headings = [True, False, False]
        kept_p, kept_h, removed = deterministic_filter(paras, headings)
        # heading survives even though it looks like a caption; formula kept
        assert kept_p == ["Figure 1: not really a heading", "$$x^2$$"]
        assert removed["killed"] == 1


class TestGatekeeperApply:
    def _state(self, paras, headings=None, subtitle=""):
        return {
            "article": {"index": 0, "title": "T", "subtitle": subtitle, "paragraphs": []},
            "english_paragraphs": paras,
            "english_headings": headings or [False] * len(paras),
        }

    def test_non_body_labels_dropped_and_reported(self, monkeypatch):
        monkeypatch.setattr(
            bg, "_classify", lambda idx, paras: ({0: "author_block", 1: "body"}, {"node": "body_gatekeeper", "input_tokens": 1, "output_tokens": 1})
        )
        out = bg.body_gatekeeper(self._state(["Florian Pargent, LMU Munich", "Real body prose."]))
        assert out["english_paragraphs"] == ["Real body prose."]
        assert any("removed 1 non-body" in e for e in out["errors"])

    def test_classifier_failure_fails_open(self, monkeypatch):
        def boom(idx, paras):
            raise RuntimeError("api down")

        monkeypatch.setattr(bg, "_classify", boom)
        paras = ["One.", "Two."]
        out = bg.body_gatekeeper(self._state(paras))
        assert out["english_paragraphs"] == paras
        assert any("keeping its 2 paragraph(s)" in e for e in out["errors"])

    def test_formulas_skip_the_llm_but_headings_are_judged(self, monkeypatch):
        seen: list[list[int]] = []

        def record(idx, paras):
            seen.append(list(idx))
            return {i: "body" for i in idx}, {"node": "body_gatekeeper", "input_tokens": 0, "output_tokens": 0}

        monkeypatch.setattr(bg, "_classify", record)
        out = bg.body_gatekeeper(
            self._state(["Intro heading", "$$E=mc^2$$", "Prose."], [True, False, False])
        )
        assert seen == [[0, 2]]  # formulas auto-kept; headings ARE classified
        assert out["english_paragraphs"] == ["Intro heading", "$$E=mc^2$$", "Prose."]

    def test_heading_styled_author_byline_dropped(self, monkeypatch):
        # Author bylines often carry heading styling — the heading flag must
        # not exempt them (observed on the Pargent paper).
        monkeypatch.setattr(
            bg,
            "_classify",
            lambda idx, paras: (
                {0: "author_block", 1: "body"},
                {"node": "body_gatekeeper", "input_tokens": 0, "output_tokens": 0},
            ),
        )
        out = bg.body_gatekeeper(
            self._state(["Florian Pargent1, Ramona Schoedel1", "Prose."], [True, False])
        )
        assert out["english_paragraphs"] == ["Prose."]

    def test_author_byline_as_subtitle_cleared(self, monkeypatch):
        # Academic papers: the segmenter takes the bold byline under the
        # title as the article subtitle — it must be judged and cleared too.
        monkeypatch.setattr(
            bg,
            "_classify",
            lambda idx, paras: (
                {0: "body", 1: "author_block"},
                {"node": "body_gatekeeper", "input_tokens": 0, "output_tokens": 0},
            ),
        )
        out = bg.body_gatekeeper(
            self._state(["Prose."], subtitle="Florian Pargent1, Ramona Schoedel1")
        )
        assert out["article"]["subtitle"] == ""
        assert out["english_paragraphs"] == ["Prose."]

    def test_real_standfirst_subtitle_kept(self, monkeypatch):
        monkeypatch.setattr(
            bg,
            "_classify",
            lambda idx, paras: (
                {0: "body", 1: "body"},
                {"node": "body_gatekeeper", "input_tokens": 0, "output_tokens": 0},
            ),
        )
        out = bg.body_gatekeeper(
            self._state(["Prose."], subtitle="A real standfirst sentence.")
        )
        assert "article" not in out  # untouched when the subtitle is body
