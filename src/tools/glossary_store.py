"""SQLite-backed store for the style-scoped terminology glossaries.

Storage layout (2.0 Phase 1):
- Live store: a single SQLite file (data/glossary.db, gitignored). SQLite
  transactions replace the old fcntl-locked JSON read-modify-write; WAL mode
  plus a busy timeout handles parallel article branches under the LangGraph
  Send fan-out, and the whole store stays one copyable file — which is what
  the 2.0 web app packages as its read-only authoritative snapshot (path A).
- Factory seeds: the version-controlled data/glossary_<style>.json files.
  On first access to a style the store auto-seeds itself from that JSON
  (idempotent), so a fresh clone or deployment bootstraps with no manual
  migration step.

Public API is unchanged from the JSON era: load_glossary / terms_by_en /
add_terms, plus remove_terms for the audit script. "First in wins" is
preserved: a term already in the store is never overwritten by a duplicate,
so the glossary stays stable once a term is published.
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
    style      TEXT NOT NULL,
    en_lower   TEXT NOT NULL,
    en         TEXT NOT NULL,
    zh         TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'uncategorized',
    source     TEXT NOT NULL DEFAULT 'web_search',
    added_date TEXT NOT NULL,
    PRIMARY KEY (style, en_lower)
);
CREATE TABLE IF NOT EXISTS seeded_styles (
    style TEXT PRIMARY KEY
);
"""


def _seed_path(style: str) -> Path:
    return DATA_DIR / f"glossary_{style}.json"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / _DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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


def _insert(conn: sqlite3.Connection, style: str, term: dict) -> bool:
    """INSERT OR IGNORE — the entry already in the store wins. Returns
    whether the row was actually inserted."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO terms (style, en_lower, en, zh, category, source, added_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            style,
            term["en"].lower(),
            term["en"],
            term["zh"],
            term.get("category", "uncategorized"),
            term.get("source", "web_search"),
            term.get("added_date") or date.today().isoformat(),
        ),
    )
    return cur.rowcount == 1


def _ensure_seeded(conn: sqlite3.Connection, style: str) -> None:
    """One-time import of the factory JSON for a style (idempotent)."""
    if conn.execute("SELECT 1 FROM seeded_styles WHERE style = ?", (style,)).fetchone():
        return
    seed = _seed_path(style)
    if seed.exists():
        doc = json.loads(seed.read_text(encoding="utf-8"))
        for term in doc.get("terms", []):
            _insert(conn, style, term)
    conn.execute("INSERT OR IGNORE INTO seeded_styles (style) VALUES (?)", (style,))


def load_glossary(style: str) -> dict:
    """Return the glossary document: {"style": ..., "terms": [...]}."""
    with _connect() as conn:
        _ensure_seeded(conn, style)
        rows = conn.execute(
            "SELECT * FROM terms WHERE style = ? ORDER BY en_lower", (style,)
        ).fetchall()
    return {"style": style, "terms": [_row_to_term(r) for r in rows]}


def terms_by_en(doc: dict) -> dict[str, dict]:
    return {t["en"].lower(): t for t in doc.get("terms", [])}


def add_terms(style: str, new_terms: list[dict]) -> list[dict]:
    """Insert terms that are not yet in the store; returns the entries that
    were actually added (existing entries win over incoming duplicates)."""
    added: list[dict] = []
    with _connect() as conn:
        _ensure_seeded(conn, style)
        for term in new_terms:
            entry = {
                "en": term["en"],
                "zh": term["zh"],
                "category": term.get("category", "uncategorized"),
                "source": term.get("source", "web_search"),
                "added_date": date.today().isoformat(),
            }
            if _insert(conn, style, entry):
                added.append(entry)
    return added


def remove_terms(style: str, en_keys: list[str]) -> list[dict]:
    """Delete the given terms (by lowercased EN key); returns the removed
    entries so callers (the audit script) can archive them reversibly."""
    removed: list[dict] = []
    with _connect() as conn:
        _ensure_seeded(conn, style)
        for key in en_keys:
            row = conn.execute(
                "SELECT * FROM terms WHERE style = ? AND en_lower = ?", (style, key.lower())
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                "DELETE FROM terms WHERE style = ? AND en_lower = ?", (style, key.lower())
            )
            removed.append(_row_to_term(row))
    return removed
