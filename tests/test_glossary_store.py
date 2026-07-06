import json

import pytest

from src.tools import glossary_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(glossary_store, "DATA_DIR", tmp_path)
    return tmp_path


def test_load_missing_glossary_returns_empty(store):
    doc = glossary_store.load_glossary("economist")
    assert doc == {"style": "economist", "terms": []}


def test_auto_seeds_from_factory_json(store):
    (store / "glossary_economist.json").write_text(
        json.dumps(
            {
                "style": "economist",
                "terms": [
                    {
                        "en": "quantitative easing",
                        "zh": "量化宽松",
                        "category": "monetary policy",
                        "source": "seed",
                        "added_date": "2026-07-03",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    doc = glossary_store.load_glossary("economist")
    terms = glossary_store.terms_by_en(doc)
    assert terms["quantitative easing"]["zh"] == "量化宽松"
    assert terms["quantitative easing"]["source"] == "seed"
    assert terms["quantitative easing"]["added_date"] == "2026-07-03"


def test_seeding_is_one_time(store):
    seed = store / "glossary_economist.json"
    seed.write_text(
        json.dumps({"terms": [{"en": "IPO", "zh": "首次公开募股（IPO）"}]}), encoding="utf-8"
    )
    glossary_store.load_glossary("economist")
    glossary_store.remove_terms("economist", ["IPO"])
    # A removed term must not resurrect from the factory JSON.
    assert glossary_store.load_glossary("economist")["terms"] == []


def test_add_and_reload(store):
    added = glossary_store.add_terms(
        "economist", [{"en": "Quantitative Easing", "zh": "量化宽松", "source": "web_search"}]
    )
    assert len(added) == 1 and added[0]["added_date"]
    doc = glossary_store.load_glossary("economist")
    assert glossary_store.terms_by_en(doc)["quantitative easing"]["zh"] == "量化宽松"


def test_existing_entry_wins_over_duplicate(store):
    glossary_store.add_terms("economist", [{"en": "IPO", "zh": "首次公开募股（IPO）"}])
    added = glossary_store.add_terms("economist", [{"en": "ipo", "zh": "别的翻译"}])
    assert added == []
    doc = glossary_store.load_glossary("economist")
    terms = glossary_store.terms_by_en(doc)
    assert len(doc["terms"]) == 1 and terms["ipo"]["zh"] == "首次公开募股（IPO）"


def test_styles_are_isolated(store):
    glossary_store.add_terms("economist", [{"en": "token", "zh": "代币"}])
    glossary_store.add_terms("academy", [{"en": "token", "zh": "token"}])
    assert glossary_store.terms_by_en(glossary_store.load_glossary("economist"))["token"]["zh"] == "代币"
    assert glossary_store.terms_by_en(glossary_store.load_glossary("academy"))["token"]["zh"] == "token"


def test_remove_terms_returns_removed_entries(store):
    glossary_store.add_terms("economist", [{"en": "state failure", "zh": "国家失败"}])
    removed = glossary_store.remove_terms("economist", ["State Failure", "not-there"])
    assert len(removed) == 1 and removed[0]["en"] == "state failure"
    assert glossary_store.load_glossary("economist")["terms"] == []


def test_available_styles_derived_from_prompt_files():
    from src.styles import available_styles

    assert available_styles() == ["academy", "economist"]
