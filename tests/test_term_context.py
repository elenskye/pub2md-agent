"""Example-sentence extraction for term_occurrences (wordbook material)."""

from src.tools.term_context import extract_example

PARAS = [
    "A dull opening paragraph.",
    "Markets wobbled. Quantitative easing returned with a vengeance! Bonds rallied.",
    "Quantitative easing also appears here, later.",
]


def test_first_sentence_containing_term():
    assert (
        extract_example("quantitative easing", PARAS)
        == "Quantitative easing returned with a vengeance!"
    )


def test_case_insensitive_match():
    assert extract_example("QUANTITATIVE EASING", PARAS).startswith("Quantitative easing")


def test_missing_term_gives_empty_string():
    assert extract_example("inflation", PARAS) == ""


def test_unsplittable_paragraph_falls_back_to_prefix():
    paras = ["no sentence punctuation here but the term appears somewhere in the flow"]
    out = extract_example("the term", paras, max_len=30)
    assert out == paras[0][:30]


def test_truncated_to_max_len():
    assert len(extract_example("quantitative easing", PARAS, max_len=10)) == 10
