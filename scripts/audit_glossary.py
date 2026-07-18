"""One-time (re-runnable) audit of researched glossary entries.

Judges every non-seed entry against the same rubric the term_verifier node
applies to new candidates. Entries judged "reject" or "rewrite" are removed
from the SQLite store and archived (with the verdict recorded) to
data/glossary_<domain>_rejected.json so the cleanup is reversible; seed
entries are never touched.

Usage:
    python -m scripts.audit_glossary [--domain econ] [--dry-run]
"""

import argparse
import json
from datetime import date
from pathlib import Path

from src.styles import available_domains
from src.tools import glossary_store
from src.tools.glossary_store import load_glossary, remove_terms
from src.tools.term_rubric import judge_terms

_BATCH = 30

# The rubric prompt is flavoured by base style; map each domain to the base
# style its papers/articles are normally read under.
_RUBRIC_STYLE = {"econ": "economist", "cs": "academy", "pm": "academy"}


def audit(domain: str, dry_run: bool) -> int:
    doc = load_glossary(domain)
    researched = [t for t in doc.get("terms", []) if t.get("source") != "seed"]
    if not researched:
        print(f"[{domain}] no researched entries to audit")
        return 0
    print(f"[{domain}] auditing {len(researched)} researched entries...")

    verdicts: dict = {}
    for i in range(0, len(researched), _BATCH):
        chunk = [t["en"] for t in researched[i : i + _BATCH]]
        chunk_verdicts, usage = judge_terms(chunk, _RUBRIC_STYLE.get(domain, "academy"))
        verdicts.update(chunk_verdicts)
        print(f"  judged {i + len(chunk)}/{len(researched)} "
              f"(tokens {usage['input_tokens']}/{usage['output_tokens']})")

    to_remove: list[dict] = []
    for term in researched:
        ruling = verdicts.get(term["en"].lower())
        if ruling and ruling["verdict"] in ("reject", "rewrite"):
            to_remove.append({**term, "verdict": ruling["verdict"],
                              "minimal_form": ruling["term"],
                              "audited_date": date.today().isoformat()})

    print(f"\n[{domain}] keep {len(doc['terms']) - len(to_remove)} · remove {len(to_remove)}")
    for r in to_remove:
        note = f" → {r['minimal_form']}" if r["verdict"] == "rewrite" else ""
        print(f"  - {r['en']} => {r['zh']}  [{r['verdict']}{note}]")

    if dry_run or not to_remove:
        print("(dry run — nothing written)" if dry_run else "(nothing to write)")
        return 0

    removed = remove_terms(domain, [r["en"] for r in to_remove])
    rejected_path = Path(glossary_store.DATA_DIR) / f"glossary_{domain}_rejected.json"
    existing = (
        json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
    )
    rejected_path.write_text(
        json.dumps(existing + to_remove, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"removed {len(removed)} from the store · archived to {rejected_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_glossary")
    parser.add_argument("--domain", default=None, choices=available_domains())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    domains = [args.domain] if args.domain else available_domains()
    for domain in domains:
        audit(domain, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
