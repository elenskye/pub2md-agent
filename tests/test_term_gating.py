"""The deterministic halves of the terminology quality gates: grounding in
the extractor, and verdict application in the verifier."""

from src.agent.nodes.term_candidate_extractor import filter_candidates
from src.tools.term_rubric import apply_verdicts

ARTICLE = (
    "Montgomery, the cradle of the Confederacy, has seen state failure and "
    "renewal. The Equal Justice Initiative opened a memorial."
)


class TestGroundingFilter:
    def test_hallucinated_term_dropped(self):
        assert filter_candidates(["quantitative easing"], ARTICLE, {}) == []

    def test_grounded_term_kept_case_insensitive(self):
        assert filter_candidates(["equal justice initiative"], ARTICLE, {}) == [
            "equal justice initiative"
        ]

    def test_known_glossary_term_dropped(self):
        glossary = {"confederacy": {"en": "Confederacy", "zh": "南部邦联"}}
        assert filter_candidates(["Confederacy"], ARTICLE, glossary) == []

    def test_overlong_phrase_dropped(self):
        long_phrase = "the cradle of the Confederacy has seen"
        assert filter_candidates([long_phrase], ARTICLE, {}) == []

    def test_non_strings_and_duplicates_dropped(self):
        out = filter_candidates([None, 42, "Confederacy", "confederacy "], ARTICLE, {})
        assert out == ["Confederacy"]


class TestApplyVerdicts:
    def test_reject_removed(self):
        verdicts = {"state failure": {"verdict": "reject", "term": ""}}
        accepted, rejected = apply_verdicts(["state failure"], verdicts, ARTICLE, {})
        assert accepted == [] and rejected == ["state failure"]

    def test_rewrite_to_grounded_minimal_form(self):
        verdicts = {
            "cradle of the confederacy": {"verdict": "rewrite", "term": "Confederacy"}
        }
        accepted, rejected = apply_verdicts(
            ["cradle of the Confederacy"], verdicts, ARTICLE, {}
        )
        assert accepted == ["Confederacy"] and rejected == []

    def test_rewrite_to_ungrounded_form_rejected(self):
        verdicts = {"cradle of the confederacy": {"verdict": "rewrite", "term": "Union"}}
        accepted, rejected = apply_verdicts(
            ["cradle of the Confederacy"], verdicts, ARTICLE, {}
        )
        assert accepted == [] and rejected == ["cradle of the Confederacy"]

    def test_rewrite_into_known_glossary_term_deduped(self):
        glossary = {"confederacy": {"en": "Confederacy", "zh": "南部邦联"}}
        verdicts = {
            "cradle of the confederacy": {"verdict": "rewrite", "term": "Confederacy"}
        }
        accepted, _ = apply_verdicts(["cradle of the Confederacy"], verdicts, ARTICLE, glossary)
        assert accepted == []

    def test_unruled_candidate_fails_open(self):
        accepted, rejected = apply_verdicts(["Equal Justice Initiative"], {}, ARTICLE, {})
        assert accepted == ["Equal Justice Initiative"] and rejected == []
