# Changelog

What has already been built. Planned work lives in [ROADMAP.md](ROADMAP.md).

Newest first. "Local only" means the change is implemented and verified on
the dev machine but not yet on the live server — v3 ships to production in
one cutover (see the roadmap).

## v3 — two-axis styles, output purity, layout accuracy (local only)

### Phase 4 — VLM layout hybrid + translation quality
- `src/tools/vlm_layout.py`: each page is rendered at 140 DPI with its
  text-layer blocks outlined and numbered; a vision model returns only
  *reading order* + *role* per block. Text always comes from the PDF text
  layer, so there is zero transcription risk. Non-body roles are dropped at
  layout time; ordered pages skip geometric column clustering. Per-page
  fail-open to the geometric path; the whole feature is off when `VLM_*`
  is unset or `VLM_LAYOUT=off`.
- Fixes two-column reading-order corruption (the dominant quality defect
  found by comparing pipeline output with a manual translation): zipped
  columns, a definition table leaking as a run-on paragraph, split
  multi-line headings — all gone on the 35-page test paper.
- Optional refine pass: a second review-and-rewrite translation call per
  batch (`--refine`, UI checkbox, `Job.refine`), ~2× translation cost.
- Owner-supplied translation seeds entered `glossary_cs` as authoritative
  `source=seed` entries; identity mappings (`mlr3 => mlr3`) are now banned
  and the existing ones were purged.
- Progress bar counts paragraphs, not batches, across named pools
  (layout 10–25, gatekeeper 35–45, translation 45–95).

### Phase 3 — Body purification + speed
- Output purity rule: a note contains the title, body text (incl. section
  headings) and display formulas — nothing else. Table regions are dropped
  outright (the old `[table omitted]` placeholder is gone).
- `src/tools/body_filters.py`: deterministic kill-regexes (emails, DOI,
  licences, corresponding-author lines, ISSN, download stamps), caption
  openers, and a references cut.
- New `body_gatekeeper` node classifies surviving paragraphs in batches
  into body / author_block / caption / footnote / reference / furniture;
  only body survives. Fail-open per batch. Headings and the article
  subtitle are classified too — bylines carry heading styling.
- Speed: concurrent translation batches (`TRANSLATE_CONCURRENCY`, default
  4), larger batch bounds, and no translation of junk. 35-page paper:
  20 min → ~5 min, 503 → 286 paragraphs.
- Audit-rejected terms became a candidate blocklist so junk cannot
  resurrect on a re-run.

### Phase 2 — Term pipeline per domain
- Max 5 term candidates per article; `term_verifier` attributes each new
  term to exactly one selected domain; research queries are domain-keyed.
- `term_occurrences` table records real example sentences for new *and*
  known terms (raw material for the planned wordbook export).
- New `glossary_conflict_auditor` node reports real cross-domain zh
  disagreements into the run summary, the run log, the job result and the
  UI.
- Glossary audit round: 44 junk terms deleted and archived; the rubric
  gained a "settled standard rendering → reject" criterion and a
  common-word brand-collision example.
- UI: custom file picker and dropdown, domain pills, percent progress bar.

### Phase 1 — Two-axis style model
- Base style (economist / academy) × domain glossaries (econ / cs / pm) as
  independent axes, free pairing with default guidance; `src/styles.py`
  derives both axes from the prompt files and the seed glossaries.
- Carried through state, graph, CLI (`--base-style`, `--domains`), the Job
  model and the UI. Pre-v3 glossary DBs auto-migrate in place on first
  connect (style→domain, economist→econ, academy→cs).

## v2 — Django web app (live)

1. Glossary moved from JSON files to SQLite (`data/glossary.db`), auto-seeded
   from the versioned seed JSONs.
2. Service layer: Job model, single-worker thread-pool executor, progress
   from `graph.stream()`, budget guard.
3. Auth: two rotatable accounts (`manage.py rotate_accounts`), one active
   session each — a new login kills the old one.
4. Single-page browser UI with marked + KaTeX preview and proper CSRF.
5. Paper-ink redesign (cream background, cinnabar accent, serif hero).
6. Hardening: currency escaping (`$86bn` → `\$86bn`) at generation time,
   clear-history + retention sweep, production settings, deployment to a
   DigitalOcean droplet (nginx + gunicorn + systemd + certbot TLS).

## v1 — Agent core (live)

1. MVP pipeline: pdf_extractor → noise_stripper → article_segmenter →
   `Send` fan-out → translator → formatter → output_writer.
2. Robustness: language-state detection, English isolation (embedded
   translations are always discarded and re-translated), OpenCC `tw2sp`
   (Traditional input → Simplified-only output), academy style.
3. Terminology system: glossaries grown via Tavily search,
   glossary-constrained translation, eval harness against a single-shot
   baseline.
4. Layout fixes, observability (run logs + LangSmith), unit tests.
5. Term quality gates (grounding filter + keep/rewrite/reject verifier
   rubric + `scripts/audit_glossary.py`); display formulas transcribed to
   LaTeX by a vision model, with a placeholder fallback when no VLM is
   configured.
