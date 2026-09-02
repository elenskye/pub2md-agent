# Roadmap

What is still planned. Finished work lives in [CHANGELOG.md](CHANGELOG.md).

Working rules for the remaining v3 phases:

- One phase at a time: plan → confirm → implement → verify with the full
  pytest suite **and** at least one real-PDF run.
- There is nowhere to ship to: the hosted deployment was retired on
  2026-09-01 and pub2md is a local tool. "Done" means green on the dev
  machine, committed to `main`, and the four documents updated.

Standing scope decisions (settled, not up for casual relitigation):

- Output purity: a note contains the title, body text and display formulas
  only — no images, tables, captions, footnotes, author blocks or
  references.
- No figure/image extraction. No VLM for inline math.
- Terminology stays a generate-critique pipeline, not a free-form
  multi-agent system.
- The Django app stays. It is the local front end — preview, KaTeX, job
  history, zip download — not a hosting artifact.

## Phase 6 — Local-first web app

The web app was built to face the public internet. Nothing serves that
purpose any more, and some of it is now pure friction.

- **Auth off-switch**: `PUB2MD_AUTH=off` (default `on`) skips login and the
  single-active-session rule when the app is bound to localhost. Keep the
  code — a shared installation may come back — but do not make the owner
  log in to translate a PDF on his own laptop.
- **Vendor KaTeX + marked** into `webapp/static/` (was in the old Phase 8).
  A local tool that needs a CDN to render a formula is broken on a train.
- **Guard rails become local defaults**: `PUB2MD_MAX_UPLOAD_MB=25` /
  `PUB2MD_MAX_PDF_PAGES=100` were anti-abuse limits for two guest accounts.
  Raise the defaults, keep them env-driven, and document the reason.

## Phase 7 — Wordbook export

`scripts/export_wordbook.py --domain econ --format md|anki-csv`, built from
approved terms × `term_occurrences`: EN / ZH / category / real example
sentences / frequency / first seen. Markdown grouped by category; the Anki
CSV imports as-is.

## Phase 8 — Inline math + scanned PDFs

- Inline math: map Unicode math-alphanumeric glyphs to plain ASCII in the
  extracted text. The display-formula VLM path is unchanged.
- Scanned PDFs: detect a sparse text layer → render pages → VLM page
  transcription → single-article pipeline entry. `SCAN_MAX_PAGES`
  (default 30) rejects oversize uploads before any spend; requires `VLM_*`.

## Phase 9 — Cleanup, eval, v3 release

- Remove the USD cost estimate (`PRICE_*`, `Job.cost_usd`, CLI line); the
  monthly budget guard switches to `PUB2MD_MONTHLY_BUDGET_TOKENS`.
- YAML front-matter in the output `.md` (title, source, date, base_style,
  domains, tags).
- **Eval overhaul, then one fresh baseline** — this gates the release,
  because the numbers in the README were last measured on the v2 pipeline.
  Fix the known weaknesses first, then re-run the full suite once and
  update the README table:
  - cross-family LLM judge (the current one shares a model family with the
    translator, so it grades itself);
  - populate `eval/references/` so the dormant paragraph-boundary F1
    metric activates;
  - add a pm test article to the manifest, and cover the v3 features the
    current metrics ignore — body purity (share of non-body lines surviving
    into the output) and reading-order correctness on two-column pages;
  - report refine-on vs refine-off as a separate row.
- Tag `v3` on `main`.

## Backlog (not scheduled)

- Demo recording for the README.
- Retire the candidate export/import path (`manage.py export_candidates`,
  `GET /api/glossary/candidates`, `audit_glossary --import-batch`) if a
  second installation never materialises. Harmless and tested; delete only
  when it is certain it will never be needed.
