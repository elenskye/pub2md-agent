# pub2md-agent

A LangGraph agent that turns a multi-article PDF (e.g. an Economist-style
issue) into one clean, bilingual (English + Simplified Chinese) Markdown file
per article — with column-aware layout parsing, article segmentation, and
style-consistent translation.

> Portfolio project. Full requirements and design decisions live in
> [CLAUDE.md](CLAUDE.md). Status: **Phase 2 (robustness) complete** —
> language-state detection, English-source isolation, Traditional→Simplified
> conversion path, two style presets (economist / academy), and graceful
> degradation throughout. Phases 3–4 (terminology system with web search,
> eval & observability) are upcoming.

## Quickstart

```bash
# deps: langgraph, langchain-openai, pymupdf, python-dotenv, pydantic
cp .env.example .env   # fill in DEEPSEEK_API_KEY
python -m src.cli path/to/issue.pdf --style economist
```

One `.md` file per detected article is written to `outputs/`, and the run
ends with a summary: files written, per-article failures, token usage and
estimated cost.

## Pipeline

```
pdf_extractor → noise_stripper → article_segmenter
    → [Send fan-out, one branch per article]
        → lang_state_detector ─┬─(English source)→ en_text_isolator → translator ─┐
                               └─(Chinese source)→ opencc_converter ──────────────┤
                                                                                   ↓
                                                              formatter → output_writer
```

- **pdf_extractor** — line-level text + coordinates + font sizes (PyMuPDF).
  Aborts if the PDF has no text layer (OCR is out of scope).
- **noise_stripper** — drops page numbers, running headers/footers, print
  artifacts and note-app export UI; in majority-English documents also drops
  any embedded Chinese translation (always re-translated from the English
  source). Reflows lines into paragraphs using per-font-size vertical-gap
  statistics and right-edge deficits, stitching paragraphs that continue
  across columns/pages.
- **article_segmenter** — font-size heading candidates, confirmed by an LLM
  that sees only headings + short previews (never the full body); rejects
  section headings inside academic papers.
- **lang_state_detector** — rule-based: Latin/Han ratio decides the source
  language; OpenCC round-trips detect simplified vs traditional script.
- **translator** — numbered batches, JSON-mode replies plus tail-repair
  parsing for guaranteed EN/ZH alignment; 2 retries per batch, then
  `[translation failed]` degradation so one bad paragraph never kills an
  article. Output: bilingual EN/ZH Markdown.
- **opencc_converter** — Chinese-source path: Traditional/mixed script is
  converted with OpenCC (`tw2sp`); output is Simplified-Chinese-only
  Markdown, no translation round-trip.
