"""Glossary audit — the local half of the closed loop (v3 Phase 5).

Terms grown at runtime are stored as CANDIDATES: usable immediately, but not
authoritative. They become authoritative only here — judged against the same
rubric the term_verifier node applies, reviewed by the owner, promoted to
approved, and written back into the version-controlled seed JSON, which is
the artifact a fresh store imports on its first connect.

    # judge the candidates a run (or a server batch) produced
    python -m scripts.audit_glossary --candidates [--domain cs] [--dry-run]

    # merge a batch exported from the server (manage.py export_candidates)
    python -m scripts.audit_glossary --import-batch candidates.json

    # regenerate the release artifact from the approved terms, then commit it
    python -m scripts.audit_glossary --regenerate-seed [--domain cs]

    # re-judge every researched entry regardless of status (the v1 sweep)
    python -m scripts.audit_glossary [--domain econ] [--dry-run]

Entries judged "reject" or "rewrite" are removed from the SQLite store and
archived with their verdict to data/glossary_<domain>_rejected.json, so the
cleanup is reversible and the rejected keys become a blocklist. Seed-sourced
entries are never judged.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from src.styles import available_domains
from src.tools import glossary_store
from src.tools.glossary_store import (
    CANDIDATE,
    approve_terms,
    import_candidates,
    load_glossary,
    remove_terms,
    write_seed,
)
from src.tools.term_rubric import judge_terms

_BATCH = 30

# The rubric prompt is flavoured by base style; map each domain to the base
# style its papers/articles are normally read under.
_RUBRIC_STYLE = {"econ": "economist", "cs": "academy", "pm": "academy"}


def _judge(domain: str, entries: list[dict]) -> dict:
    verdicts: dict = {}
    for i in range(0, len(entries), _BATCH):
        chunk = [t["en"] for t in entries[i : i + _BATCH]]
        chunk_verdicts, usage = judge_terms(chunk, _RUBRIC_STYLE.get(domain, "academy"))
        verdicts.update(chunk_verdicts)
        print(f"  judged {i + len(chunk)}/{len(entries)} "
              f"(tokens {usage['input_tokens']}/{usage['output_tokens']})")
    return verdicts


def _archive(domain: str, entries: list[dict]) -> Path:
    path = Path(glossary_store.DATA_DIR) / f"glossary_{domain}_rejected.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    path.write_text(
        json.dumps(existing + entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def audit(domain: str, dry_run: bool, candidates_only: bool) -> int:
    doc = load_glossary(domain, status=CANDIDATE if candidates_only else None)
    entries = [t for t in doc.get("terms", []) if t.get("source") != "seed"]
    label = "candidate" if candidates_only else "researched"
    if not entries:
        print(f"[{domain}] no {label} entries to audit")
        return 0
    print(f"[{domain}] auditing {len(entries)} {label} entries...")

    verdicts = _judge(domain, entries)

    to_remove: list[dict] = []
    to_keep: list[dict] = []
    for term in entries:
        ruling = verdicts.get(term["en"].lower())
        if ruling and ruling["verdict"] in ("reject", "rewrite"):
            to_remove.append({**term, "verdict": ruling["verdict"],
                              "minimal_form": ruling["term"],
                              "audited_date": date.today().isoformat()})
        else:
            to_keep.append(term)

    print(f"\n[{domain}] keep {len(to_keep)} · remove {len(to_remove)}")
    for r in to_remove:
        note = f" → {r['minimal_form']}" if r["verdict"] == "rewrite" else ""
        print(f"  - {r['en']} => {r['zh']}  [{r['verdict']}{note}]")
    if candidates_only:
        for k in to_keep:
            print(f"  + {k['en']} => {k['zh']}  [promote to approved]")

    if dry_run:
        print("(dry run — nothing written)")
        return 0

    if to_remove:
        removed = remove_terms(domain, [r["en"] for r in to_remove])
        print(f"removed {len(removed)} from the store · archived to {_archive(domain, to_remove)}")
    if candidates_only and to_keep:
        promoted = approve_terms(domain, [k["en"] for k in to_keep])
        print(f"promoted {len(promoted)} candidate(s) to approved")
        print("next: --regenerate-seed, then commit the seed JSON")
    elif not to_remove:
        print("(nothing to write)")
    return 0


def regenerate(domain: str) -> None:
    path, count = write_seed(domain)
    print(f"[{domain}] wrote {count} approved term(s) → {path}")


def import_batch(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries = doc.get("terms", doc) if isinstance(doc, dict) else doc
    imported = import_candidates(entries)
    by_domain: dict[str, int] = {}
    for entry in imported:
        by_domain[entry.get("domain", "?")] = by_domain.get(entry.get("domain", "?"), 0) + 1
    skipped = len(entries) - len(imported)
    detail = ", ".join(f"{d}: {n}" for d, n in sorted(by_domain.items())) or "none"
    print(f"imported {len(imported)} candidate(s) ({detail}) · skipped {skipped} "
          f"(already present or audit-rejected)")


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_glossary")
    parser.add_argument("--domain", default=None, choices=available_domains())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--candidates", action="store_true",
        help="Judge only candidate entries; keeps are promoted to approved",
    )
    parser.add_argument(
        "--regenerate-seed", action="store_true",
        help="Write the approved terms back to data/glossary_<domain>.json",
    )
    parser.add_argument(
        "--import-batch", type=Path, default=None,
        help="Merge a candidate batch exported from the server",
    )
    args = parser.parse_args()

    if args.import_batch:
        import_batch(args.import_batch)
        return 0

    domains = [args.domain] if args.domain else available_domains()
    if args.regenerate_seed:
        for domain in domains:
            regenerate(domain)
        return 0

    for domain in domains:
        audit(domain, args.dry_run, args.candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
