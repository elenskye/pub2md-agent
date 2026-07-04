from eval.metrics import adherence_rate, consistency_rate, term_occurrences

GLOSSARY = {
    "national guard": {"en": "National Guard", "zh": "国民警卫队"},
    "ice": {"en": "ICE", "zh": "移民及海关执法局（ICE）"},
    "posse comitatus act": {"en": "Posse Comitatus Act", "zh": "《地方保安队法》（Posse Comitatus Act)"},
}


def pair(en, zh):
    return {"en": en, "zh": zh, "failed": False}


def test_word_boundary_prevents_ice_matching_justice():
    occ = term_occurrences([pair("The justice department acted.", "司法部采取了行动。")], GLOSSARY)
    assert occ == []


def test_adherent_occurrence(self=None):
    occ = term_occurrences(
        [pair("The National Guard was deployed.", "国民警卫队被部署。")], GLOSSARY
    )
    assert len(occ) == 1 and occ[0]["hit"]


def test_parenthetical_gloss_core_counts_as_hit():
    occ = term_occurrences([pair("ICE agents arrived.", "移民及海关执法局的人员到达。")], GLOSSARY)
    assert len(occ) == 1 and occ[0]["hit"]


def test_failed_pairs_are_skipped():
    occ = term_occurrences(
        [{"en": "The National Guard.", "zh": "[translation failed]", "failed": True}], GLOSSARY
    )
    assert occ == []


def test_adherence_and_consistency_rates():
    pairs = [
        pair("The National Guard was deployed.", "国民警卫队被部署。"),
        pair("The National Guard stayed.", "国民卫队留下了。"),  # non-adherent rendering
        pair("ICE agents arrived.", "移民及海关执法局（ICE）的人员到达。"),
    ]
    occ = term_occurrences(pairs, GLOSSARY)
    rate, n = adherence_rate(occ)
    assert n == 3 and abs(rate - 2 / 3) < 1e-9
    # National Guard occurs twice with differing renderings → inconsistent;
    # ICE occurs once → excluded from the multi-occurrence denominator.
    c_rate, c_terms = consistency_rate(occ)
    assert c_terms == 1 and c_rate == 0.0
