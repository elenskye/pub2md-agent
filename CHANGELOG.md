# Changelog

What has already been built. Planned work lives in [ROADMAP.md](ROADMAP.md).

Newest first.

## Phase 6 — Local-first web app

The web app was built to face the public internet. With no hosted instance,
parts of it were friction rather than protection.

- **Login wall is now a switch.** `PUB2MD_AUTH=off` (settings
  `AUTH_ENABLED`) drops the login page and the one-session-per-account
  rule; `/api/me` answers `{"auth": false}` so the UI skips straight to the
  tool. Default is **on**, and `off` is *refused* when `DJANGO_DEBUG=false`
  — a served instance always has a wall, because an open pub2md hands out
  the API keys in `.env`. The auth tests pin `AUTH_ENABLED=True` so the
  suite no longer depends on the local `.env`.
- **No CDN.** marked 12.0.2 and KaTeX 0.16.11 are vendored into
  `webapp/static/vendor/` (woff2 faces only, the woff/ttf sources stripped
  from the CSS: 632 KB total). The page now issues zero external requests,
  so formulas render offline.
- **Guard rails re-tuned for one user**: upload limits 25 MB → 100 MB and
  100 → 500 pages, still env-driven. The monthly budget guard stays as it
  is — it protects the owner's own wallet, not a stranger's.

## Hosted deployment retired (2026-09-01)

The DigitalOcean droplet behind pub2md.duckdns.org is gone; pub2md is a
local tool again. It had run **one** job in two months, which did not
justify the bill. Everything on it was backed up first — the whole
`/opt/pub2md-agent` tree, both SQLite databases (consistency snapshots plus
plain-text dumps), the certbot-rewritten nginx site and the systemd unit,
verified file-by-file against server checksums, in
`~/Documents/pub2md-server-backup-2026-09-01/`. The 14 glossary terms the
server had grown and the local store had never seen were exported as a v3
candidate batch. The Django app **stays** — it is the local front end, and
nothing about it was hosting-specific: every production setting was already
env-driven. A deployment is expected again eventually, so the cloud pieces
are parked rather than deleted: `deploy/` (nginx + systemd) carries a
PARKED banner, and gunicorn moved to the optional `server` extra in
`pyproject.toml`. Cloud plans are off the roadmap until the owner asks for
them; this file is the only place the hosted era is described.

## v3 — two-axis styles, output purity, layout accuracy

### First closed-loop audit + UI refresh
- Ran the Phase 5 loop for real on the 52 candidates the migration exposed:
  **21 promoted** (cs 3 / econ 16 / pm 2), **31 rejected** and archived
  (mostly settled textbook terms — logistic regression, random forest,
  junk bonds — plus proper nouns the rubric refuses). Seeds regenerated
  from the approved set: cs 66, econ 106, pm 2, with the DB and the seed
  files now identical and zero candidates outstanding. The 34 stale
  audit-rejected entries that had lingered in the seed JSONs are gone.
- New `general` base style: neutral written Chinese for any publication
  (reports, documentation, essays), no journalistic or academic register.
- Glossary domains are now optional. No selection means "translate without
  a glossary": the term pipeline is skipped entirely, and `general`
  preselects nothing. `--domains` with no value does the same on the CLI.
- UI: `How to Use` dialog replaces every `?` tooltip; the refine checkbox
  became a second submit button (`Translate` / `Refined Translation`);
  copy and capitalization tidied; the Markdown hint line removed.

### Markdown direct translation
- Upload or pass a `.md` file and get one Chinese-only `.md` back with its
  structure intact. Separate graph (`build_md_graph`: read → glossary →
  translate → write); the PDF stages never run.
- Structure is preserved by the program, not by the model
  (`src/tools/md_fences.py`): the document is cut into a literal skeleton
  plus translatable slots, and the invariant is that rebuilding with zero
  translations returns the source byte-for-byte.
- Translated: prose, headings, wrapped list items, table cells, comments
  inside code blocks, mermaid labels, and the annotation column of a
  plain-text directory tree. Untouched: code, YAML front matter, pipes and
  bullets, inline code, URLs, math and HTML — the last four are swapped for
  ⟦n⟧ placeholders while a slot is out with the model, and a placeholder the
  model drops is recovered rather than lost.
- Slots that already contain Han characters are converted
  Traditional→Simplified locally instead of being sent to the model, so a
  Chinese `.md` costs nothing and an English one is never double-translated.
- Base style and glossary domains apply as usual; no new terms are
  researched on this path (owner's decision — direct translation must be
  fast and must not grow the glossary unaudited). `--refine` still works.

### Phase 5 — Glossary path B (closed loop)
- `terms.status`: runtime-grown terms are **candidates** (usable at once by
  every run, but not authoritative); the version-controlled seed JSON holds
  the **approved** terms and is the release artifact.
- The seed import is no longer one-shot. `seeded_domains` stores the seed
  file's SHA-256; a changed file triggers an incremental re-import in which
  an approved seed entry overwrites a candidate duplicate. Audit-rejected
  keys are skipped, so a re-seed cannot resurrect a deleted term.
- Server half: `manage.py export_candidates [--domain] [--output]` and the
  login-protected `GET /api/glossary/candidates`, which download the same
  JSON batch — collecting terms no longer needs an SSH session.
- Local half: `audit_glossary --import-batch <file>` merges a batch,
  `--candidates` judges only candidates (keep → promoted to approved,
  reject/rewrite → removed and archived), `--regenerate-seed` writes the
  approved terms back to `data/glossary_<domain>.json`.
- Migrating the existing DB classified the drift it was built to expose:
  63/90/0 approved and 10/38/4 candidates (cs/econ/pm) awaiting audit. The
  stale seeds still listed 34 audit-rejected terms; the blocklist kept every
  one of them out, and regenerating the seeds will drop them for good.

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

## v2 — Django web app

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
   DigitalOcean droplet (nginx + gunicorn + systemd + certbot TLS) —
   retired 2026-09-01, see the entry at the top.

## v1 — Agent core

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
