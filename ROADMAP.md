# Roadmap

What is still planned. Finished work lives in [CHANGELOG.md](CHANGELOG.md).

Working rules for the remaining v3 phases:

- One phase at a time: plan → confirm → implement → verify with the full
  pytest suite **and** at least one real-PDF run.
- v3 is developed and tested locally only. The live server stays on the
  current code until Phase 8; there is no CI/CD, nothing reaches it
  without a manual `git pull`.

Standing scope decisions (settled, not up for casual relitigation):

- Output purity: a note contains the title, body text and display formulas
  only — no images, tables, captions, footnotes, author blocks or
  references.
- No figure/image extraction. No VLM for inline math.
- Terminology stays a generate-critique pipeline, not a free-form
  multi-agent system.

## Phase 5 — Glossary path B (closed loop)

Runtime term additions become `status=candidate` (usable locally, not
authoritative); `manage.py export_candidates` produces a JSON batch behind
the login; `audit_glossary` is extended to review candidate batches with the
rubric plus a human pass; the regenerated seed JSONs are the release
artifact. A seed-file hash in `seeded_domains` triggers incremental
re-import, with approved entries winning over candidate duplicates.

## Phase 6 — Wordbook export

`scripts/export_wordbook.py --domain econ --format md|anki-csv`, built from
approved terms × `term_occurrences`: EN / ZH / category / real example
sentences / frequency / first seen. Markdown grouped by category; the Anki
CSV imports as-is.

## Phase 7 — Inline math + scanned PDFs

- Inline math: map Unicode math-alphanumeric glyphs to plain ASCII in the
  extracted text. The display-formula VLM path is unchanged.
- Scanned PDFs: detect a sparse text layer → render pages → VLM page
  transcription → single-article pipeline entry. `SCAN_MAX_PAGES`
  (default 30) rejects oversize uploads before any spend; requires `VLM_*`.

## Phase 8 — Cleanup, eval, production cutover

- Remove the USD cost estimate (`PRICE_*`, `Job.cost_usd`, CLI line); the
  monthly budget guard switches to `PUB2MD_MONTHLY_BUDGET_TOKENS`.
- Vendor KaTeX + marked into `webapp/static/` (no CDN dependency).
- YAML front-matter in the output `.md` (title, source, date, base_style,
  domains, tags).
- **Eval overhaul, then one fresh baseline** — this must happen before the
  cutover, because the numbers in the README were last measured on the v2
  pipeline. Fix the known weaknesses first, then re-run the full suite once
  and update the README table:
  - cross-family LLM judge (the current one shares a model family with the
    translator, so it grades itself);
  - populate `eval/references/` so the dormant paragraph-boundary F1
    metric activates;
  - add a pm test article to the manifest, and cover the v3 features the
    current metrics ignore — body purity (share of non-body lines surviving
    into the output) and reading-order correctness on two-column pages;
  - report refine-on vs refine-off as a separate row.
- Server cutover — the only production-touching step of v3: pull, pip,
  migrate, seed re-import, env changes, collectstatic, restart.

## Backlog (not scheduled)

- Demo recording for the README.
