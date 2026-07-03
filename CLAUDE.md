# Pub2MD-Agent — Project Requirements

**Type:** Portfolio project (LangGraph agent engineering demo)
**Target audience:** AI Agent / ML internship hiring managers (Singapore market)
**Owner:** Elen (undergraduate, Chongqing University → NUS Singapore)

> This document is the source of truth for scope and design decisions. It was produced through an iterative planning conversation and should be read in full by any coding agent (Claude Code, Codex, etc.) before writing code.

---

## 1. Problem Statement

The owner regularly reads long-form journalism (e.g. *The Economist*) and academic papers (computer science / AI) as PDFs. The current manual workflow is:

1. Copy text out of a PDF — column-based layouts break paragraph flow, and page numbers/headers get glued onto sentence boundaries.
2. Paste into an LLM chat, ask for a Simplified Chinese translation.
3. Manually assemble a bilingual document and import it into Bear (note-taking app).

This is repetitive, error-prone (broken paragraphs, inconsistent terminology across articles), and does not scale to multi-article PDFs (e.g. a full magazine issue).

## 2. Goals

Build a LangGraph-based agent that takes a single PDF (which may contain **multiple articles**) and produces one clean, bilingual (EN + Simplified Chinese) Markdown file **per article**, with terminology that stays consistent across every article ever processed, in a given "style."

This project exists primarily to demonstrate agent-engineering competence for a job search, not to be a general-purpose translation product. Every design decision should be defensible in an interview: *why did you build it this way, what did you try that didn't work, what would you do differently at scale.*

### Capabilities to demonstrate (hard requirements)
- Multi-step planning / task decomposition (not single-shot Q&A)
- Real multi-tool orchestration, with results fed back into the reasoning loop
- Cross-step state management (LangGraph `Send` map-reduce over multiple articles per PDF)
- Error handling & graceful degradation (retries, partial failure handling)
- Quantitative evaluation with a baseline comparison

## 3. Functional Scope

### 3.1 Input
- One PDF file, digital (text-layer) source **only** for the MVP. Scanned/photographed PDFs requiring true OCR are an explicit **future extension**, not in scope for phases 1–3.
- A PDF may contain **one or many articles**. The agent must detect article boundaries and produce one output file per article.
- Source language state per article may vary:
  - English only
  - English + an existing Chinese translation already embedded (Traditional or Simplified)
  - Chinese only (rare edge case)
- **Regardless of whether a Chinese translation already exists in the source, the agent always re-translates from the English text itself**, to guarantee consistent style and terminology. Existing translations are discarded, not reused or graded.

### 3.2 Output
- One bilingual (English + Simplified Chinese) Markdown file per detected article.
- File is written to a local `outputs/` directory. **Bear integration is out of scope** — the user imports files into Bear manually.
- Every report/output must be free of page-number/header noise inherited from the PDF.

### 3.3 Style system
- Two presets at launch: `economist` (default) and `academy` (computer science / AI academic papers).
- Style is selected **manually** via a run parameter (e.g. CLI flag or config), not auto-detected. Auto-detection is a possible future phase, not in MVP.
- Style is not just a tone preset. It determines:
  1. The system prompt used by the translator node (tone, register, and — critically — whether certain technical terms are localized or left in English; e.g. Academy style keeps "Transformer", "token", "SOTA" untranslated per academic convention, while Economist style localizes almost everything, including acronyms like GDP/IPO, with a Chinese gloss).
  2. Which glossary file is read from and written to (glossaries are style-scoped, not global).
  3. The search query context used when researching unknown terms (e.g. append "经济学人" vs "学术论文" to the query).

### 3.4 Terminology consistency system
- Each style ships with a **seed glossary** (see `glossary_economist.json` and `glossary_academy.json`, delivered alongside this document).
- During translation, when the agent encounters a specialized/technical term that is not already in the active style's glossary:
  1. It is flagged as a candidate by an extraction step (LLM-based, scoped to already-loaded glossary to avoid duplicate work).
  2. The agent calls a real web search tool (Tavily) to research the term's standard translation, with the search query shaped by the active style (journal/domain context).
  3. The resolved translation is written back into that style's glossary file, tagged with its source (`seed` / `web_search` / `llm_fallback`) and date, so the glossary grows across runs.
- This is the project's main "real tool use in the reasoning loop" showcase — search results must influence the final translation, not just be logged.

## 4. Non-Functional Requirements

### 4.1 Cost control (carried through the whole project, not an afterthought)
1. Default to a cheap model during development and evaluation. **Model provider: DeepSeek**, accessed through its OpenAI-compatible API (`ChatOpenAI` with a custom `base_url`, so no DeepSeek-specific SDK dependency is needed).
2. Provider + model name must be configurable via `.env`, never hardcoded.
3. Trim/summarize raw tool output (PDF text blocks, search results) before it reaches the LLM context.
4. Enable prompt caching where the underlying API supports it.
5. Design the eval script to support batch-style execution (no hard time pressure).
6. Set sane `max_tokens` ceilings per node.
7. Log token usage and estimated cost per run.

### 4.2 Language convention
- Conversation with the owner: Chinese.
- All repository deliverables (README, code comments, commit messages, docstrings, this document): **English**.

## 5. Architecture

### 5.1 State shape (top level)

| Field | Description |
|---|---|
| `pdf_path` | Input file path |
| `style` | `"economist"` \| `"academy"`, provided at run time, defaults to `economist` |
| `raw_blocks` | Text blocks extracted from the PDF, with layout coordinates |
| `cleaned_text` | After column-reflow and page-number/header noise stripping |
| `articles` | List of per-article sub-states produced by `article_segmenter`, fanned out via LangGraph `Send` |
| `errors` | Run-level error log |

### 5.2 Per-article sub-state

| Field | Description |
|---|---|
| `title` | Detected article title (used for output filename) |
| `raw_text` | This article's slice of `cleaned_text` |
| `has_english` | Whether English source paragraphs were found |
| `script_state` | `simplified` \| `traditional` \| `mixed` (only relevant when `has_english` is false) |
| `english_paragraphs` | Isolated English paragraphs (existing Chinese translation, if any, discarded here) |
| `translated_paragraphs` | Bilingual paragraph pairs after translation |
| `new_terms` | Terms researched and added to the glossary during this run |
| `bilingual_md` | Final assembled Markdown for this article |
| `errors`, `retry_count` | Per-article error handling |

### 5.3 Node list and control flow

```
pdf_extractor
   → noise_stripper
   → article_segmenter (rule-based heading candidates + LLM confirmation)
   → [LangGraph Send: fan out per article]
        → lang_state_detector (rule-based: CJK ratio, simplified/traditional char-set check)
        → en_text_isolator (drop any existing Chinese translation; keep English only)
             (if has_english is false and script is traditional → opencc_converter, then done)
        → style_glossary_loader (loads data/glossary_<style>.json)
        → term_candidate_extractor (LLM, scoped against already-loaded glossary)
             → [if unknown terms found] term_researcher (Tavily search, style-aware query)
                  → glossary_updater (writes resolved term back to the style's glossary file)
        → translator (style-specific system prompt + full glossary as translation constraints)
        → formatter (assembles bilingual Markdown, adds title/source/disclaimer metadata)
        → output_writer (writes one .md file per article to outputs/)
```

**Error handling policy:**
- `pdf_extractor` failure (e.g. no text layer found) → abort the run with a clear error; do not attempt a degraded partial extraction, since an incomplete source makes every downstream step unreliable.
- `translator` failure on a single paragraph → retry up to 2 times; if still failing, keep the original English paragraph in place, mark it `[translation failed]`, and continue with the rest of the article rather than failing the whole article.
- `term_researcher` failure (search API error or no usable result) → fall back to the LLM's own best-guess translation for that term, tag it `llm_fallback` in the glossary, and surface it in the final report/eval output as something that should be manually reviewed.

## 6. Repository Structure

```
pub2md-agent/
├── README.md                       # English, portfolio-facing
├── PROJECT_SPEC.md                 # This document (or equivalent)
├── .env.example
├── pyproject.toml
├── src/
│   ├── agent/
│   │   ├── graph.py                 # LangGraph graph assembly
│   │   ├── state.py                 # State schemas (TypedDict/Pydantic)
│   │   └── nodes/
│   │       ├── pdf_extractor.py
│   │       ├── noise_stripper.py
│   │       ├── article_segmenter.py
│   │       ├── lang_state_detector.py
│   │       ├── en_text_isolator.py
│   │       ├── opencc_converter.py
│   │       ├── style_glossary_loader.py
│   │       ├── term_candidate_extractor.py
│   │       ├── term_researcher.py
│   │       ├── glossary_updater.py
│   │       ├── translator.py
│   │       ├── formatter.py
│   │       └── output_writer.py
│   ├── tools/
│   │   ├── pdf_layout_parser.py     # Column-aware text/coordinate extraction
│   │   ├── glossary_store.py        # Read/write for style-scoped glossary JSON
│   │   └── web_search_tool.py       # Tavily wrapper
│   ├── prompts/
│   │   ├── economist_style.md
│   │   └── academy_style.md
│   └── config.py                    # Provider/model config from .env
├── data/
│   ├── glossary_economist.json      # Seeded (delivered separately)
│   └── glossary_academy.json        # Seeded (delivered separately)
├── eval/
│   ├── test_articles/               # Sample PDFs + reference translations
│   ├── run_eval.py
│   └── metrics.py
├── tests/
└── outputs/                         # Generated bilingual .md files (gitignored)
```

## 7. Evaluation Design

- **Baseline:** the raw extracted PDF text (no column reflow, no article segmentation, no glossary) is handed to the LLM in a single shot with a generic "translate this" prompt.
- **Pub2MD-Agent:** the full pipeline above.
- **Metrics:**
  1. Paragraph-boundary accuracy against a hand-checked reference.
  2. Terminology consistency rate — the % of glossary terms translated identically across multiple articles/runs. This is the headline metric, since it is the owner's core, self-identified pain point.
  3. LLM-as-judge fluency/accuracy score.
  4. Multi-article split accuracy (does the agent produce exactly one file per article, correctly bounded) — evaluated against the sample PDF delivered with this spec, which contains 4 distinct articles.
- Test set: 15–20 items, built from real PDFs the owner already reads, seeded with the sample PDF used during planning (a 4-article Economist-style issue with page-number noise and pre-existing bilingual text — good adversarial coverage for the noise-stripping and re-translation requirements).

## 8. Phased Implementation Plan

**Phase 1 — MVP**
`pdf_extractor` → `noise_stripper` → `article_segmenter` → (single style, English-only path) `translator` → `formatter` → `output_writer`. Prove the multi-article split and column-reflow work on the sample PDF before adding anything else.

**Phase 2 — Robustness**
Add `lang_state_detector`, `en_text_isolator`, `opencc_converter`; retries and graceful degradation; multi-style support (`economist` / `academy` switch, per-style prompts).

**Phase 3 — Terminology system**
`style_glossary_loader`, `term_candidate_extractor`, `term_researcher` (Tavily), `glossary_updater`. This is also where the eval set and baseline comparison get built, since terminology consistency is the metric that depends on this system existing.

**Phase 4 — Polish**
Observability (Langfuse/LangSmith); README with architecture diagram (Mermaid), demo recording, "design decisions & pitfalls" section; unit tests.

## 9. Explicit Non-Goals (for this project)

- Bear (or any note-app) API integration.
- Scanned/image PDF OCR.
- Batch/whole-issue ingestion in one run (single-PDF-at-a-time is fine; a PDF may itself contain multiple articles, which the agent must still split correctly).
- Reusing or grading any translation already present in the source PDF.
- Auto-detection of style — always explicitly specified per run for now.
