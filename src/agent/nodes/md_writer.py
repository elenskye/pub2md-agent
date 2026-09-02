"""Reassemble the translated Markdown and write it out.

Structure comes from the literal pieces, text from the translations — a slot
without a translation falls back to its English source, so a partially
failed run still produces a valid document.
"""

from datetime import date
from pathlib import Path

from src.agent.state import ArticleResult, PipelineState
from src.agent.nodes.output_writer import DEFAULT_OUTPUT_DIR, _slugify
from src.tools.md_fences import rebuild, slots


def md_writer(state: PipelineState) -> dict:
    pieces = state.get("md_pieces", [])
    translations = state.get("md_translations", {})
    source = Path(state["md_path"])
    title = state.get("md_title") or source.stem

    body = rebuild(pieces, translations)
    domains = ", ".join(state.get("domains", []))
    style = f"{state['base_style']} × {domains}" if domains else f"{state['base_style']}, no glossary"
    # The web app stores every upload as input.md; md_source_name carries the
    # name the user actually uploaded so the footer credits the real file.
    source_name = state.get("md_source_name") or source.name
    footer = (
        f"\n\n---\n\n*Translated from `{source_name}` by pub2md-agent "
        f"({style}) on {date.today().isoformat()} · "
        f"Machine translation — verify before quoting.*\n"
    )

    out_dir = Path(state.get("output_dir") or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Named after the document's own title, like the PDF path — the web app
    # stores uploads as "input.md", so the source stem is meaningless there.
    path = out_dir / f"{_slugify(title)}-zh.md"
    path.write_text(body.rstrip("\n") + footer, encoding="utf-8")

    entries = slots(pieces)
    failed = sum(1 for e in entries if e["id"] not in translations)
    result = ArticleResult(
        title=title,
        output_path=str(path),
        n_paragraphs=len(entries),
        n_failed=failed,
        mode="markdown",
        pairs=[],
    )
    return {"results": [result]}
