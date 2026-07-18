"""SQLite-backed store for the domain-scoped terminology glossaries.

Storage layout (v3 Phase 1 — two-axis style model):
- Live store: a single SQLite file (data/glossary.db, gitignored). SQLite
  transactions replace the old fcntl-locked JSON read-modify-write; WAL mode
  plus a busy timeout handles parallel article branches under the LangGraph
  Send fan-out, and the whole store stays one copyable file — which is what
  the web app packages as its read-only authoritative snapshot (path A).
- Factory seeds: the version-controlled data/glossary_<domain>.json files.
  On first access to a domain the store auto-seeds itself from that JSON
  (idempotent), so a fresh clone or deployment bootstraps with no manual
  migration step.

Glossaries are keyed by DOMAIN (econ, cs, pm, ...), not by the old
monolithic style names. Databases created before v3 are migrated in place
on first connect (column rename + economist→econ / academy→cs value map),
so both the dev machine and the server upgrade by just pulling the code.

Public API keeps the shape from the style era: load_glossary /
terms_by_en / add_terms, plus remove_terms for the audit script.
"First in wins" is preserved: a term already in the store is never
overwritten by a duplicate, so the glossary stays stable once published.
"""

import json
import sqlite3
from datetime import date
from pathlib import Path

# Anchored to the repo root (not the process CWD): the CLI runs from the
# repo root but the Django app runs from webapp/, and a relative path would
# silently give each its own empty store.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_NAME = "glossary.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS terms (
    domain     TEXT NOT NULL,
    en_lower   TEXT NOT NULL,
    en         TEXT NOT NULL,
    zh         TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'uncategorized',
    source     TEXT NOT NULL DEFAULT 'web_search',
    added_date TEXT NOT NULL,
    PRIMARY KEY (domain, en_lower)
);
CREATE TABLE IF NOT EXISTS seeded_domains (
    domain TEXT PRIMARY KEY
);
"""

# Pre-v3 monolithic style names → v3 domain slugs.
_LEGACY_DOMAIN_MAP = {"economist": "econ", "academy": "cs"}


def _seed_path(domain: str) -> Path:
    return DATA_DIR / f"glossary_{domain}.json"


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    """In-place upgrade of a pre-v3 database (style column / style names).
    Runs before the CREATE IF NOT EXISTS schema so the renamed tables are
    what the schema sees. Idempotent: a migrated or fresh DB is untouched."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(terms)")]
    if "style" in columns:
        conn.execute("ALTER TABLE terms RENAME COLUMN style TO domain")
        for old, new in _LEGACY_DOMAIN_MAP.items():
            conn.execute("UPDATE terms SET domain = ? WHERE domain = ?", (new, old))
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "seeded_styles" in tables:
        conn.execute("CREATE TABLE IF NOT EXISTS seeded_domains (domain TEXT PRIMARY KEY)")
        for (old,) in conn.execute("SELECT style FROM seeded_styles").fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO seeded_domains (domain) VALUES (?)",
                (_LEGACY_DOMAIN_MAP.get(old, old),),
            )
        conn.execute("DROP TABLE seeded_styles")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / _DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _migrate_legacy(conn)
    conn.executescript(_SCHEMA)
    return conn


def _row_to_term(row: sqlite3.Row) -> dict:
    return {
        "en": row["en"],
        "zh": row["zh"],
        "category": row["category"],
        "source": row["source"],
        "added_date": row["added_date"],
    }


def _insert(conn: sqlite3.Connection, domain: str, term: dict) -> bool:
    """INSERT OR IGNORE — the entry already in the store wins. Returns
    whether the row was actually inserted."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO terms (domain, en_lower, en, zh, category, source, added_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            domain,
            term["en"].lower(),
            term["en"],
            term["zh"],
            term.get("category", "uncategorized"),
            term.get("source", "web_search"),
            term.get("added_date") or date.today().isoformat(),
        ),
    )
    return cur.rowcount == 1


def _ensure_seeded(conn: sqlite3.Connection, domain: str) -> None:
    """One-time import of the factory JSON for a domain (idempotent)."""
    if conn.execute("SELECT 1 FROM seeded_domains WHERE domain = ?", (domain,)).fetchone():
        return
    seed = _seed_path(domain)
    if seed.exists():
        doc = json.loads(seed.read_text(encoding="utf-8"))
        for term in doc.get("terms", []):
            _insert(conn, domain, term)
    conn.execute("INSERT OR IGNORE INTO seeded_domains (domain) VALUES (?)", (domain,))


def load_glossary(domain: str) -> dict:
    """Return the glossary document: {"domain": ..., "terms": [...]}."""
    with _connect() as conn:
        _ensure_seeded(conn, domain)
        rows = conn.execute(
            "SELECT * FROM terms WHERE domain = ? ORDER BY en_lower", (domain,)
        ).fetchall()
    return {"domain": domain, "terms": [_row_to_term(r) for r in rows]}


def load_merged_glossary(domains: list[str]) -> dict[str, dict]:
    """Merged lowercased-EN → entry mapping for the selected domains.
    Selection order is the precedence order: on an EN-key collision the
    earlier domain wins (Phase 2 adds explicit conflict reporting)."""
    merged: dict[str, dict] = {}
    for domain in domains:
        for key, term in terms_by_en(load_glossary(domain)).items():
            merged.setdefault(key, term)
    return merged


def terms_by_en(doc: dict) -> dict[str, dict]:
    return {t["en"].lower(): t for t in doc.get("terms", [])}


def add_terms(domain: str, new_terms: list[dict]) -> list[dict]:
    """Insert terms that are not yet in the store; returns the entries that
    were actually added (existing entries win over incoming duplicates)."""
    added: list[dict] = []
    with _connect() as conn:
        _ensure_seeded(conn, domain)
        for term in new_terms:
            entry = {
                "en": term["en"],
                "zh": term["zh"],
                "category": term.get("category", "uncategorized"),
                "source": term.get("source", "web_search"),
                "added_date": date.today().isoformat(),
            }
            if _insert(conn, domain, entry):
                added.append(entry)
    return added


def remove_terms(domain: str, en_keys: list[str]) -> list[dict]:
    """Delete the given terms (by lowercased EN key); returns the removed
    entries so callers (the audit script) can archive them reversibly."""
    removed: list[dict] = []
    with _connect() as conn:
        _ensure_seeded(conn, domain)
        for key in en_keys:
            row = conn.execute(
                "SELECT * FROM terms WHERE domain = ? AND en_lower = ?", (domain, key.lower())
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                "DELETE FROM terms WHERE domain = ? AND en_lower = ?", (domain, key.lower())
            )
            removed.append(_row_to_term(row))
    return removed
