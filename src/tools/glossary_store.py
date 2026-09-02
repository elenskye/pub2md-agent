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

Phase 5 (closed loop) adds `terms.status`:
- `candidate` — grown at runtime by term_researcher. Usable immediately
  (the translator loads every status), but NOT authoritative: it has not
  passed the rubric plus a human review.
- `approved` — imported from the version-controlled seed JSON, which is the
  release artifact regenerated after an audit.

The seed import is therefore no longer a one-shot: `seeded_domains` stores
the seed file's hash and a changed file triggers an incremental re-import,
where an approved seed entry overwrites a candidate duplicate. Audit-
rejected keys are skipped during import, so a term the owner deleted cannot
resurrect through a re-seed.

Public API keeps the shape from the style era: load_glossary /
terms_by_en / add_terms, plus remove_terms for the audit script.
"First in wins" is preserved within a status: a term already in the store
is never overwritten by a runtime duplicate, so the glossary stays stable
once published. The seed channel is the one deliberate exception.
"""

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

# Anchored to the repo root (not the process CWD): the CLI runs from the
# repo root but the Django app runs from webapp/, and a relative path would
# silently give each its own empty store.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_NAME = "glossary.db"

APPROVED = "approved"
CANDIDATE = "candidate"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS terms (
    domain     TEXT NOT NULL,
    en_lower   TEXT NOT NULL,
    en         TEXT NOT NULL,
    zh         TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'uncategorized',
    source     TEXT NOT NULL DEFAULT 'web_search',
    added_date TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'approved',
    PRIMARY KEY (domain, en_lower)
);
CREATE TABLE IF NOT EXISTS seeded_domains (
    domain    TEXT PRIMARY KEY,
    seed_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS term_occurrences (
    domain        TEXT NOT NULL,
    en_lower      TEXT NOT NULL,
    article_title TEXT NOT NULL,
    sentence      TEXT NOT NULL,
    added_date    TEXT NOT NULL
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


def _seed_doc(domain: str) -> dict:
    seed = _seed_path(domain)
    if not seed.exists():
        return {}
    return json.loads(seed.read_text(encoding="utf-8"))


def _seed_keys(domain: str) -> set[str]:
    return {t["en"].lower() for t in _seed_doc(domain).get("terms", [])}


def _seed_digest(domain: str) -> str:
    seed = _seed_path(domain)
    if not seed.exists():
        return ""
    return hashlib.sha256(seed.read_bytes()).hexdigest()


def _migrate_status(conn: sqlite3.Connection) -> None:
    """Phase 5 upgrade of a pre-status database. Existing rows are classified
    against the versioned seeds: what a seed file contains is approved, and
    everything else was grown at runtime and becomes a candidate awaiting
    audit — which is exactly the drift the closed loop exists to resolve."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(terms)")]
    if columns and "status" not in columns:
        conn.execute(f"ALTER TABLE terms ADD COLUMN status TEXT NOT NULL DEFAULT '{CANDIDATE}'")
        for (domain,) in conn.execute("SELECT DISTINCT domain FROM terms").fetchall():
            conn.executemany(
                "UPDATE terms SET status = ? WHERE domain = ? AND en_lower = ?",
                [(APPROVED, domain, key) for key in _seed_keys(domain)],
            )
    seeded = [row[1] for row in conn.execute("PRAGMA table_info(seeded_domains)")]
    if seeded and "seed_hash" not in seeded:
        # Empty hash ≠ any real digest, so the next access re-imports once.
        conn.execute("ALTER TABLE seeded_domains ADD COLUMN seed_hash TEXT NOT NULL DEFAULT ''")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATA_DIR / _DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _migrate_legacy(conn)
    _migrate_status(conn)
    conn.executescript(_SCHEMA)
    return conn


def _row_to_term(row: sqlite3.Row) -> dict:
    return {
        "en": row["en"],
        "zh": row["zh"],
        "category": row["category"],
        "source": row["source"],
        "added_date": row["added_date"],
        "domain": row["domain"],
        "status": row["status"],
    }


def _insert(conn: sqlite3.Connection, domain: str, term: dict, status: str) -> bool:
    """INSERT OR IGNORE — the entry already in the store wins. Returns
    whether the row was actually inserted."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO terms "
        "(domain, en_lower, en, zh, category, source, added_date, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            domain,
            term["en"].lower(),
            term["en"],
            term["zh"],
            term.get("category", "uncategorized"),
            term.get("source", "web_search"),
            term.get("added_date") or date.today().isoformat(),
            status,
        ),
    )
    return cur.rowcount == 1


def _import_seed_term(conn: sqlite3.Connection, domain: str, term: dict) -> None:
    """Write one seed entry as approved. Unlike the runtime path this DOES
    overwrite an existing row: the seed is the audited release artifact, so
    an approved entry wins over the candidate a run happened to grow first."""
    if _insert(conn, domain, term, APPROVED):
        return
    conn.execute(
        "UPDATE terms SET en = ?, zh = ?, category = ?, source = ?, status = ? "
        "WHERE domain = ? AND en_lower = ?",
        (
            term["en"],
            term["zh"],
            term.get("category", "uncategorized"),
            term.get("source", "web_search"),
            APPROVED,
            domain,
            term["en"].lower(),
        ),
    )


def _ensure_seeded(conn: sqlite3.Connection, domain: str) -> None:
    """Import the factory JSON when it is new or has changed since the last
    import (hash-gated, so an unchanged seed costs one hash and nothing
    else). Audit-rejected keys are skipped — a re-seed must never resurrect
    a term the owner deleted."""
    digest = _seed_digest(domain)
    row = conn.execute(
        "SELECT seed_hash FROM seeded_domains WHERE domain = ?", (domain,)
    ).fetchone()
    if row is not None and row["seed_hash"] == digest:
        return
    blocked = rejected_keys([domain])
    for term in _seed_doc(domain).get("terms", []):
        if term["en"].lower() not in blocked:
            _import_seed_term(conn, domain, term)
    conn.execute(
        "INSERT INTO seeded_domains (domain, seed_hash) VALUES (?, ?) "
        "ON CONFLICT(domain) DO UPDATE SET seed_hash = excluded.seed_hash",
        (domain, digest),
    )


def load_glossary(domain: str, status: str | None = None) -> dict:
    """Return the glossary document: {"domain": ..., "terms": [...]}.
    Every status is included by default — candidates are usable locally the
    moment they are researched; `status` narrows it for export/audit."""
    query = "SELECT * FROM terms WHERE domain = ?"
    params: list = [domain]
    if status:
        query += " AND status = ?"
        params.append(status)
    with _connect() as conn:
        _ensure_seeded(conn, domain)
        rows = conn.execute(query + " ORDER BY en_lower", params).fetchall()
    return {"domain": domain, "terms": [_row_to_term(r) for r in rows]}


def load_merged_glossary(domains: list[str]) -> dict[str, dict]:
    """Merged lowercased-EN → entry mapping for the selected domains.
    Selection order is the precedence order: on an EN-key collision the
    earlier domain wins."""
    merged, _ = merge_with_conflicts(domains)
    return merged


def merge_with_conflicts(domains: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Like load_merged_glossary, but also reports the collisions where the
    selected domains actually disagree on the translation (identical zh in
    both domains is not worth surfacing). Conflicts are what the job summary
    shows the user for cross-domain runs."""
    merged: dict[str, dict] = {}
    conflicts: dict[str, dict] = {}
    for domain in domains:
        for key, term in terms_by_en(load_glossary(domain)).items():
            winner = merged.get(key)
            if winner is None:
                merged[key] = term
            elif term["zh"] != winner["zh"]:
                conflict = conflicts.setdefault(
                    key,
                    {
                        "en": winner["en"],
                        "chosen_domain": winner["domain"],
                        "chosen_zh": winner["zh"],
                        "shadowed": [],
                    },
                )
                conflict["shadowed"].append({"domain": term["domain"], "zh": term["zh"]})
    return merged, list(conflicts.values())


def record_occurrences(entries: list[dict]) -> None:
    """Append term sightings (one row per term × article) to the wordbook
    log. Deliberately not deduplicated: repeat sightings ARE the frequency
    signal the Phase 4 wordbook export sorts by; re-running the same PDF
    inflates counts, which is acceptable at this project's scale."""
    if not entries:
        return
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO term_occurrences (domain, en_lower, article_title, sentence, added_date) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    e["domain"],
                    e["en"].lower(),
                    e["article_title"],
                    e["sentence"],
                    e.get("added_date") or date.today().isoformat(),
                )
                for e in entries
            ],
        )


def rejected_keys(domains: list[str]) -> set[str]:
    """Lowercased EN keys of terms an audit removed for these domains.
    Used as a candidate blocklist: without it, re-running a PDF quietly
    resurrects terms the owner deliberately deleted (observed with
    "midnight basketball" after the 2026-07 audit)."""
    keys: set[str] = set()
    for domain in domains:
        path = DATA_DIR / f"glossary_{domain}_rejected.json"
        if path.exists():
            for entry in json.loads(path.read_text(encoding="utf-8")):
                keys.add(entry["en"].lower())
    return keys


def occurrences_for(domain: str) -> list[dict]:
    """All recorded sightings for a domain, oldest first (Phase 4 export)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM term_occurrences WHERE domain = ? ORDER BY rowid", (domain,)
        ).fetchall()
    return [dict(r) for r in rows]


def terms_by_en(doc: dict) -> dict[str, dict]:
    return {t["en"].lower(): t for t in doc.get("terms", [])}


def add_terms(domain: str, new_terms: list[dict], status: str = CANDIDATE) -> list[dict]:
    """Insert terms that are not yet in the store; returns the entries that
    were actually added (existing entries win over incoming duplicates).
    Runtime additions are candidates: usable at once, authoritative only
    once an audit promotes them and they land in a regenerated seed."""
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
                "status": status,
            }
            if _insert(conn, domain, entry, status):
                added.append(entry)
    return added


def candidates_for(domains: list[str] | None = None) -> list[dict]:
    """Every candidate entry, oldest first — the export batch the owner
    audits offline. Without `domains`, all domains present in the store."""
    query = "SELECT * FROM terms WHERE status = ?"
    params: list = [CANDIDATE]
    if domains:
        query += f" AND domain IN ({','.join('?' * len(domains))})"
        params += list(domains)
    with _connect() as conn:
        for domain in domains or []:
            _ensure_seeded(conn, domain)
        rows = conn.execute(query + " ORDER BY added_date, en_lower", params).fetchall()
    return [_row_to_term(r) for r in rows]


def candidate_batch(domains: list[str] | None = None) -> dict:
    """The exportable batch: every candidate the deployment grew, tagged with
    an export date. Consumed by `manage.py export_candidates`, the download
    endpoint, and `audit_glossary --import-batch` on the other side."""
    from src.styles import available_domains

    return {
        "exported_at": date.today().isoformat(),
        "terms": candidates_for(domains or available_domains()),
    }


def approve_terms(domain: str, en_keys: list[str]) -> list[dict]:
    """Promote candidates to approved (audit verdict "keep"). Returns the
    promoted entries; keys that are absent or already approved are ignored."""
    promoted: list[dict] = []
    with _connect() as conn:
        for key in en_keys:
            row = conn.execute(
                "SELECT * FROM terms WHERE domain = ? AND en_lower = ? AND status = ?",
                (domain, key.lower(), CANDIDATE),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                "UPDATE terms SET status = ? WHERE domain = ? AND en_lower = ?",
                (APPROVED, domain, key.lower()),
            )
            promoted.append({**_row_to_term(row), "status": APPROVED})
    return promoted


def import_candidates(entries: list[dict]) -> list[dict]:
    """Merge an exported batch (e.g. from the server) into the local store as
    candidates. Entries carry their own domain; rejected keys are skipped."""
    imported: list[dict] = []
    for entry in entries:
        domain = entry.get("domain")
        if not domain or entry["en"].lower() in rejected_keys([domain]):
            continue
        imported += add_terms(domain, [entry], status=CANDIDATE)
    return imported


def write_seed(domain: str) -> tuple[Path, int]:
    """Regenerate data/glossary_<domain>.json from the approved terms — the
    release artifact that ships to the server. The stored hash is refreshed
    in the same breath, so writing a seed never triggers a pointless
    re-import of what the DB already holds."""
    doc = _seed_doc(domain)
    terms = [
        {k: t[k] for k in ("en", "zh", "category", "source", "added_date")}
        for t in load_glossary(domain, status=APPROVED)["terms"]
    ]
    payload = {
        "domain": domain,
        "description": doc.get(
            "description", f"Seed terminology glossary for the {domain} domain."
        ),
        "terms": terms,
    }
    path = _seed_path(domain)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO seeded_domains (domain, seed_hash) VALUES (?, ?) "
            "ON CONFLICT(domain) DO UPDATE SET seed_hash = excluded.seed_hash",
            (domain, _seed_digest(domain)),
        )
    return path, len(terms)


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
