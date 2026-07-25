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
        accepted, rejected, _ = apply_verdicts(["state failure"], verdicts, ARTICLE, {})
        assert accepted == [] and rejected == ["state failure"]

    def test_rewrite_to_grounded_minimal_form(self):
        verdicts = {
            "cradle of the confederacy": {"verdict": "rewrite", "term": "Confederacy"}
        }
        accepted, rejected, _ = apply_verdicts(
            ["cradle of the Confederacy"], verdicts, ARTICLE, {}
        )
        assert accepted == ["Confederacy"] and rejected == []

    def test_rewrite_to_ungrounded_form_rejected(self):
        verdicts = {"cradle of the confederacy": {"verdict": "rewrite", "term": "Union"}}
        accepted, rejected, _ = apply_verdicts(
            ["cradle of the Confederacy"], verdicts, ARTICLE, {}
        )
        assert accepted == [] and rejected == ["cradle of the Confederacy"]

    def test_rewrite_into_known_glossary_term_deduped(self):
        glossary = {"confederacy": {"en": "Confederacy", "zh": "南部邦联"}}
        verdicts = {
            "cradle of the confederacy": {"verdict": "rewrite", "term": "Confederacy"}
        }
        accepted, _, _ = apply_verdicts(["cradle of the Confederacy"], verdicts, ARTICLE, glossary)
        assert accepted == []

    def test_unruled_candidate_fails_open(self):
        accepted, rejected, _ = apply_verdicts(["Equal Justice Initiative"], {}, ARTICLE, {})
        assert accepted == ["Equal Justice Initiative"] and rejected == []


class TestDomainAttribution:
    def test_judged_domain_kept_and_fallback_applied(self):
        verdicts = {
            "confederacy": {"verdict": "keep", "term": "", "domain": "pm"},
        }
        accepted, _, term_domains = apply_verdicts(
            ["Confederacy", "Equal Justice Initiative"], verdicts, ARTICLE, {}, "cs"
        )
        assert accepted == ["Confederacy", "Equal Justice Initiative"]
        assert term_domains == {"Confederacy": "pm", "Equal Justice Initiative": "cs"}

    def test_rewrite_carries_its_rulings_domain(self):
        verdicts = {
            "cradle of the confederacy": {
                "verdict": "rewrite", "term": "Confederacy", "domain": "pm",
            }
        }
        _, _, term_domains = apply_verdicts(
            ["cradle of the Confederacy"], verdicts, ARTICLE, {}, "cs"
        )
        assert term_domains == {"Confederacy": "pm"}


class TestRejectedBlocklist:
    def test_audit_rejected_term_never_resurrects(self):
        blocked = {"confederacy"}
        assert filter_candidates(["Confederacy"], ARTICLE, {}, blocked) == []

    def test_unblocked_terms_pass(self):
        assert filter_candidates(["Confederacy"], ARTICLE, {}, {"other term"}) == ["Confederacy"]


class TestIdentityMapping:
    def test_exact_and_case_insensitive_identity(self):
        from src.tools.term_rubric import is_identity_mapping

        assert is_identity_mapping("mlr3", "mlr3")
        assert is_identity_mapping("tensor2tensor", "Tensor2Tensor")
        assert not is_identity_mapping("random forest", "随机森林")
        assert not is_identity_mapping("IPO", "首次公开募股（IPO）")


class TestCandidateCap:
    def test_capped_at_five_per_article(self):
        text = "alpha beta gamma delta epsilon zeta eta"
        terms = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
        assert len(filter_candidates(terms, text, {})) == 5
