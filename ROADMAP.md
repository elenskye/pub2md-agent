# Roadmap

What is still planned. Finished work lives in [CHANGELOG.md](CHANGELOG.md).

Working rules for the remaining v3 phases:

- One phase at a time: plan → confirm → implement → verify with the full
  pytest suite **and** at least one real run.
- Done means green on the dev machine, committed to `main`, and the four
  documents updated. There is no deployment step.

Standing scope decisions (settled, not up for casual relitigation):

- Output purity: a note contains the title, body text and display formulas
  only — no images, tables, captions, footnotes, author blocks or
  references.
- No figure/image extraction. No VLM for inline math.
- Terminology stays a generate-critique pipeline, not a free-form
  multi-agent system.
- The Django app stays: it is the local front end — preview, KaTeX, job
  history, zip download — and the agent never depends on it.

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
- Glossary enforcement over-applies on general prose (`features => 特征值`
  turning "both features off" into "两个特征值均关闭"). Inherent to hard
  glossary constraints; a fix would mean softening enforcement for
  non-technical sentences, which risks the consistency the glossary exists
  for. Choosing the right `--domains` is the current answer.
