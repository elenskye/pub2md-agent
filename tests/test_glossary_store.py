import json
import sqlite3

import pytest

from src.tools import glossary_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(glossary_store, "DATA_DIR", tmp_path)
    return tmp_path


def test_load_missing_glossary_returns_empty(store):
    doc = glossary_store.load_glossary("econ")
    assert doc == {"domain": "econ", "terms": []}


def test_auto_seeds_from_factory_json(store):
    (store / "glossary_econ.json").write_text(
        json.dumps(
            {
                "domain": "econ",
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
    doc = glossary_store.load_glossary("econ")
    terms = glossary_store.terms_by_en(doc)
    assert terms["quantitative easing"]["zh"] == "量化宽松"
    assert terms["quantitative easing"]["source"] == "seed"
    assert terms["quantitative easing"]["added_date"] == "2026-07-03"


def test_seeding_is_one_time(store):
    seed = store / "glossary_econ.json"
    seed.write_text(
        json.dumps({"terms": [{"en": "IPO", "zh": "首次公开募股（IPO）"}]}), encoding="utf-8"
    )
    glossary_store.load_glossary("econ")
    glossary_store.remove_terms("econ", ["IPO"])
    # A removed term must not resurrect from the factory JSON.
    assert glossary_store.load_glossary("econ")["terms"] == []


def test_add_and_reload(store):
    added = glossary_store.add_terms(
        "econ", [{"en": "Quantitative Easing", "zh": "量化宽松", "source": "web_search"}]
    )
    assert len(added) == 1 and added[0]["added_date"]
    doc = glossary_store.load_glossary("econ")
    assert glossary_store.terms_by_en(doc)["quantitative easing"]["zh"] == "量化宽松"


def test_existing_entry_wins_over_duplicate(store):
    glossary_store.add_terms("econ", [{"en": "IPO", "zh": "首次公开募股（IPO）"}])
    added = glossary_store.add_terms("econ", [{"en": "ipo", "zh": "别的翻译"}])
    assert added == []
    doc = glossary_store.load_glossary("econ")
    terms = glossary_store.terms_by_en(doc)
    assert len(doc["terms"]) == 1 and terms["ipo"]["zh"] == "首次公开募股（IPO）"


def test_domains_are_isolated(store):
    glossary_store.add_terms("econ", [{"en": "token", "zh": "代币"}])
    glossary_store.add_terms("cs", [{"en": "token", "zh": "token"}])
    assert glossary_store.terms_by_en(glossary_store.load_glossary("econ"))["token"]["zh"] == "代币"
    assert glossary_store.terms_by_en(glossary_store.load_glossary("cs"))["token"]["zh"] == "token"


def test_merged_glossary_earlier_domain_wins(store):
    glossary_store.add_terms("econ", [{"en": "token", "zh": "代币"}])
    glossary_store.add_terms("cs", [{"en": "token", "zh": "token"}, {"en": "SOTA", "zh": "SOTA"}])
    merged = glossary_store.load_merged_glossary(["econ", "cs"])
    assert merged["token"]["zh"] == "代币"  # precedence: selection order
    assert merged["sota"]["zh"] == "SOTA"  # non-conflicting terms merge in
    assert glossary_store.load_merged_glossary(["cs", "econ"])["token"]["zh"] == "token"


def test_remove_terms_returns_removed_entries(store):
    glossary_store.add_terms("econ", [{"en": "state failure", "zh": "国家失败"}])
    removed = glossary_store.remove_terms("econ", ["State Failure", "not-there"])
    assert len(removed) == 1 and removed[0]["en"] == "state failure"
    assert glossary_store.load_glossary("econ")["terms"] == []


def test_legacy_style_db_migrates_in_place(store):
    """A pre-v3 database (style column, monolithic style names) upgrades on
    first connect: economist→econ, academy→cs, seeded_styles→seeded_domains."""
    conn = sqlite3.connect(store / "glossary.db")
    conn.executescript(
        """
        CREATE TABLE terms (
            style TEXT NOT NULL, en_lower TEXT NOT NULL, en TEXT NOT NULL,
            zh TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'uncategorized',
            source TEXT NOT NULL DEFAULT 'web_search', added_date TEXT NOT NULL,
            PRIMARY KEY (style, en_lower)
        );
        CREATE TABLE seeded_styles (style TEXT PRIMARY KEY);
        INSERT INTO terms VALUES
            ('economist', 'ipo', 'IPO', '首次公开募股（IPO）', 'finance', 'seed', '2026-07-01'),
            ('academy', 'token', 'token', 'token', 'ml', 'seed', '2026-07-01');
        INSERT INTO seeded_styles VALUES ('economist'), ('academy');
        """
    )
    conn.commit()
    conn.close()

    assert glossary_store.terms_by_en(glossary_store.load_glossary("econ"))["ipo"]["zh"] == (
        "首次公开募股（IPO）"
    )
    assert glossary_store.terms_by_en(glossary_store.load_glossary("cs"))["token"]["zh"] == "token"
    # Old tables are gone; the migrated seed markers prevent re-seeding.
    with sqlite3.connect(store / "glossary.db") as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "seeded_styles" not in tables
        seeded = {r[0] for r in conn.execute("SELECT domain FROM seeded_domains")}
    assert {"econ", "cs"} <= seeded


def test_base_styles_derived_from_prompt_files():
    from src.styles import available_base_styles

    assert available_base_styles() == ["academy", "economist"]


def test_domains_derived_from_seed_files():
    from src.styles import available_domains, default_domains

    assert available_domains() == ["cs", "econ", "pm"]
    assert default_domains("economist") == ["econ"]
    assert default_domains("academy") == ["cs"]
    # Unknown base style still yields a usable, valid default.
    assert default_domains("mystery") == ["cs"]
