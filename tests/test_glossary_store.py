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


def test_written_file_is_valid_utf8_json(store):
    glossary_store.add_terms("academy", [{"en": "token", "zh": "token"}])
    raw = (store / "glossary_academy.json").read_text(encoding="utf-8")
    assert "token" in raw and json.loads(raw)["terms"][0]["en"] == "token"
