"""Read/write access to the style-scoped glossary JSON files.

Glossaries live in data/glossary_<style>.json and grow across runs as
term_researcher resolves new terms. Writes are guarded by an exclusive file
lock and re-read the file first: article branches run in parallel under the
LangGraph Send fan-out, and two branches may resolve terms at the same time.
On a conflict (same term resolved twice) the entry already on disk wins, so
later runs stay consistent with whatever was published first.
"""

import fcntl
import json
from datetime import date
from pathlib import Path

DATA_DIR = Path("data")


def glossary_path(style: str) -> Path:
    return DATA_DIR / f"glossary_{style}.json"


def load_glossary(style: str) -> dict:
    """Return the glossary document; terms as a dict keyed by lowercased EN."""
    path = glossary_path(style)
    if not path.exists():
        return {"style": style, "terms": []}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def terms_by_en(doc: dict) -> dict[str, dict]:
    return {t["en"].lower(): t for t in doc.get("terms", [])}


def add_terms(style: str, new_terms: list[dict]) -> list[dict]:
    """Append terms that are not yet in the file; returns the entries that
    were actually added (existing entries win over incoming duplicates)."""
    path = glossary_path(style)
    path.parent.mkdir(exist_ok=True)
    added: list[dict] = []
    # Lock a sidecar so the JSON file itself can be replaced atomically.
    lock_path = path.with_suffix(".lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        doc = load_glossary(style)
        known = terms_by_en(doc)
        for term in new_terms:
            key = term["en"].lower()
            if key in known:
                continue
            entry = {
                "en": term["en"],
                "zh": term["zh"],
                "category": term.get("category", "uncategorized"),
                "source": term.get("source", "web_search"),
                "added_date": date.today().isoformat(),
            }
            doc.setdefault("terms", []).append(entry)
            known[key] = entry
            added.append(entry)
        if added:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            tmp.replace(path)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return added
