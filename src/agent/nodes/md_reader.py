"""Read a Markdown file and cut it into literal/translatable pieces.

The .md path is deliberately short (read → translate → write): a Markdown
file needs none of the PDF pipeline's layout parsing, article segmentation
or body purification — it is already clean, structured text, and the
structure is preserved programmatically by src/tools/md_fences.py.
"""

from pathlib import Path

from src.agent.state import Article, PipelineState
from src.tools.md_fences import segment, slots


def md_reader(state: PipelineState) -> dict:
    path = Path(state["md_path"])
    text = path.read_text(encoding="utf-8")
    pieces = segment(text)

    # First ATX heading, else the file name — used for the output filename
    # and the run summary. The uploaded name beats the stored one ("input").
    title = Path(state.get("md_source_name") or path.name).stem
    for line in text.split("\n"):
        if line.startswith("#"):
            title = line.lstrip("#").strip() or title
            break

    # A single synthetic "article" keeps the run summary, the job progress
    # and the result shape identical to the PDF path.
    article = Article(index=0, title=title, subtitle="", paragraphs=[], headings=[])
    return {
        "md_pieces": pieces,
        "md_title": title,
        "articles": [article],
        "errors": [] if slots(pieces) else [f"md_reader: {path.name} has no translatable text"],
    }
