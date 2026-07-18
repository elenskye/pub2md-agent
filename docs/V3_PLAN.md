# v3 Plan — agreed 2026-07-18

Scope agreed with the owner. All v3 work is developed and tested locally;
the deployed server is untouched until the Phase 6 cutover (see the v3
deployment rule in CLAUDE.md). Every phase ends with full pytest green plus
at least one real-PDF run; the owner verifies and commits himself.

## Agreed scope decisions

- Term candidates: **max 5 per article** (was 8); pipeline stays inside the
  per-article subgraph.
- Styles become a **two-axis model**: base style (single-select: economist,
  academy) × domain glossaries (multi-select: econ, cs, pm). The old
  monolithic `academy` style is replaced by `academy × cs`; `pm` is a new
  domain (owner supplies test articles).
- Inline math: **no VLM transcription**. Math-font glyphs in prose are
  normalized to plain ASCII letters/digits; only display formulas keep the
  existing VLM path (with its `[formula omitted]`-style placeholder
  fallback).
- **No figure/image extraction** — out of scope by owner decision (the
  product is a .md skeleton for the user's own notes, not a complete note).
- **Scanned/image-only PDF support is in scope**, with a page cap.
- The USD cost estimate is removed; the monthly budget guard is kept but
  switched to a token basis.
- Glossary Path B (server candidates → local audited merge → seed release)
  is in scope.
- Wordbook export (glossary as an English-learning vocabulary product) is
  in scope.

---

## Phase 1 — Two-axis style model (base style × domains) — DONE 2026-07-18

The foundation everything terminology-related builds on; do it first.
Implemented as planned; owner decisions applied: domain slugs econ/cs/pm,
free pairing with default-domain guidance, scan page cap 30 (Phase 5).
Deviation from the draft below: the glossary DB migration is automatic
(in-place upgrade on first connect in glossary_store), so no manual
`manage.py` command is needed for it — the server upgrades by pulling the
code; only the Django `migrate` step remains for the Job table.

- Split the single `style` into `base_style` (prompt, tone, layout rules;
  from `src/prompts/<name>_style.md`) and `domains: list[str]` (which
  glossaries load; from `data/glossary_<domain>.json` seed files).
  `src/styles.py` grows `available_base_styles()` + `available_domains()`,
  both file-derived — adding a domain stays a zero-UI-change drop-in.
- Renames/migrations:
  - `glossary_economist.json` → `glossary_econ.json`;
    `glossary_academy.json` → `glossary_cs.json`; new (small or empty)
    `glossary_pm.json`.
  - `glossary.db`: `terms.style` / `seeded_styles.style` values
    `economist`→`econ`, `academy`→`cs` (column semantics become "domain";
    optionally rename the column).
  - Webapp `Job` model: `style` → `base_style` + `domains`; migration maps
    historical rows (`economist`→economist×[econ], `academy`→academy×[cs]).
  - A `manage.py` migration command usable both locally and on the server
    at cutover time (server DB has live rows with the old names).
  - `eval/manifest.json` and tests updated.
- UI: two controls — base style radio + domain multi-select. Defaults:
  economist→[econ], academy→[cs]. Any combination is allowed (free
  pairing), defaults just guide.
- Exit: pytest green; real runs of the Economist magazine
  (economist×econ) and "Attention is All You Need" (academy×cs).

Decision points (owner): final domain slugs (econ/cs/pm); free pairing vs
restricting domains per base style (plan assumes free).

## Phase 2 — Term pipeline updates

- Candidate cap 5 per article (`_MAX_CANDIDATES` 8→5 + prompt text).
- Multi-domain read: translator sees the merged glossaries of all selected
  domains. On an EN-key conflict between domains, the user's domain
  selection order wins; all conflicts are listed explicitly in the job
  summary (useful signal for cross-domain papers).
- Strict write scoping: `term_verifier`'s rubric gains a domain-attribution
  judgement — every accepted new term is assigned to exactly one of the
  selected domains; `glossary_updater` writes only to that domain.
- New `term_occurrences` table: (domain, en_lower, article_title, sentence,
  date). Recorded for new candidates AND for known-glossary hits during
  translation, so frequency and real example sentences accumulate. The
  authoritative `terms` rows stay immutable (first-in-wins untouched).
- Exit: pytest green; real run selecting two domains on one PDF (owner's
  pm test article if available, else academy×[cs,pm] on the Attention
  paper) verifying conflict reporting and single-domain attribution.

## Phase 3 — Glossary Path B (closed loop)

- `terms.status` column: `approved` (from seed) / `candidate` (added at
  runtime). Candidates still participate in translation on the machine
  that created them (local consistency), but are not authoritative.
- Export: `manage.py export_candidates` → JSON batch (term + source
  article + example sentences from `term_occurrences`). Transport is
  manual: a login-protected download endpoint in the webapp (or scp —
  owner's choice; no auto-sync protocol).
- Audit & merge: extend `scripts/audit_glossary.py` to take a candidate
  batch → run the term_verifier keep/rewrite/reject rubric → present a
  review table for the owner's final call → merge accepted terms into the
  local authoritative DB → **regenerate the versioned
  `glossary_<domain>.json` seeds**. The seed files become the release
  artifact; git history is the glossary audit log.
- Re-seeding: `seeded_styles` stores the seed file hash; on hash change the
  store re-runs an incremental INSERT OR IGNORE import. An incoming
  approved term that duplicates a local candidate upgrades it to approved
  in place; candidates never override approved rows.
- Exit: full loop rehearsed locally end-to-end (run → export → audit →
  merge → seed regen → reseed picks it up), plus pytest green.

## Phase 4 — Wordbook export

- `scripts/export_wordbook.py --domain econ --format md|anki-csv`.
- Entry: EN / ZH / category / real example sentence(s) from read articles /
  frequency / first-seen date, from `terms` (approved only) joined with
  `term_occurrences`.
- Markdown layout grouped by category; Anki CSV importable as-is.
- Exit: generate a real Economist wordbook from accumulated local data.

## Phase 5 — Layout fixes & scanned-PDF input

- Author-block exemption: on page 1, near the title, regions with short
  lines / email addresses / superscript markers / affiliation keywords
  (University, Institute, @…) are body text, never `[table omitted]`.
  Regression test: the Attention paper.
- Inline math normalization: map Unicode math-alphanumeric glyphs (math
  italic/bold letters, digits) to plain ASCII in extracted text; symbols
  with no ASCII mapping are dropped or kept verbatim (pick in
  implementation). No VLM involved. Display-formula path unchanged.
- Scanned-PDF support:
  - Detection: text layer absent or sparse (extractable chars/page below a
    threshold) → OCR route.
  - OCR route: render each page to an image (PyMuPDF, ~150 DPI) → existing
    VLM (`VLM_*` block) transcribes the page to plain markdown-ish text →
    result enters the normal pipeline **as a single-article document** (no
    font/layout signals → no multi-article segmentation, no heading tiers;
    the VLM is asked to mark obvious headings).
  - Page cap: `SCAN_MAX_PAGES` env (default 30); over-cap uploads are
    rejected with a clear message before any spend.
  - Cost/latency estimate (documented for the owner): ~1–2.5K vision
    tokens + ~0.5–1.5K output tokens per page → a 30-page scan is on the
    order of 10⁵ tokens, i.e. **well under $0.05** at qwen3-vl-8b-class
    OpenRouter pricing. The real constraints are latency (~2–5 s/page,
    sequential → 1–3 min per document) and per-page failure handling —
    hence the page cap, not cost.
  - Requires `VLM_*` configured; without it, scanned PDFs are rejected
    with an explanatory error (same spirit as the formula placeholder
    fallback).
- Exit: pytest green; one real scanned-PDF run + Attention regression run.

Decision points (owner): `SCAN_MAX_PAGES` default; whether scanned inputs
should also be restricted to specific base styles.

## Phase 6 — Web cleanup, eval, release cutover

- Remove the USD cost estimate: drop `PRICE_INPUT_PER_M` /
  `PRICE_OUTPUT_PER_M`, `Job.cost_usd` display, CLI cost line. The monthly
  budget guard (webapp/jobs/views.py) switches from
  `PUB2MD_MONTHLY_BUDGET_USD` to a monthly **token** cap
  (`PUB2MD_MONTHLY_BUDGET_TOKENS`); runaway-spend protection is kept.
- Vendor KaTeX + marked into `webapp/static/` (drop the jsdelivr CDN
  dependency — users in China hit CDN flakiness).
- YAML front-matter in every output .md (formatter): title, source pdf,
  date, base_style, domains, tags.
- Eval: LLM-judge moved to a different model family than the translator
  (removes the documented self-grading bias); pm test article added to
  `eval/manifest.json`; optionally start populating `eval/references/`.
- **Server cutover** (the only server-touching step of v3): one
  consolidated update guide — git pull, pip, Django migrations, the
  Phase 1 glossary/Job migration command, seed re-import, env changes
  (remove `PRICE_*`, add token budget, optional `SCAN_MAX_PAGES`),
  collectstatic, restart. Owner executes it manually per DEPLOYMENT.md
  conventions.
- Exit: full pytest; all test PDFs re-run locally; full local webapp
  end-to-end pass; then the owner deploys.
