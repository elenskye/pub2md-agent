# pub2md-agent

A LangGraph agent that turns a multi-article PDF (e.g. an Economist-style
issue) into one clean, bilingual (English + Simplified Chinese) Markdown file
per article — with column-aware layout parsing, article segmentation, and
style-consistent translation.

> Portfolio project. Full requirements and design decisions live in
> [CLAUDE.md](CLAUDE.md). Status: **Phase 1 (MVP) complete** — layout
> extraction, noise stripping, article segmentation with LLM confirmation,
> Send fan-out per article, batched translation with retries, Markdown
> output. Phases 2–4 (multi-style, terminology system with web search, eval
> & observability) are upcoming.

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
        → translator → formatter → output_writer
```

- **pdf_extractor** — line-level text + coordinates + font sizes (PyMuPDF).
  Aborts if the PDF has no text layer (OCR is out of scope).
- **noise_stripper** — drops page numbers, header furniture and any embedded
  Chinese translation (always re-translated from the English source), then
  reflows lines into paragraphs using vertical gaps and font-size changes,
  stitching paragraphs that continue across columns/pages.
- **article_segmenter** — font-size heading candidates, confirmed by an LLM
  that sees only headings + short previews (never the full body).
- **translator** — numbered batches, JSON-mode replies for guaranteed
  EN/ZH alignment; 2 retries per batch, then `[translation failed]`
  degradation so one bad paragraph never kills an article.
