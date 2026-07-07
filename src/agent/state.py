"""State schemas for the pub2md-agent LangGraph pipeline."""

import operator
from typing import Annotated, TypedDict


class Line(TypedDict, total=False):
    """One text line extracted from the PDF, with layout coordinates."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float
    math_only: bool  # every span set in a LaTeX math font (display math)
    special: str  # synthetic marker: "formula" | "table"
    clip: tuple  # (x0, y0, x1, y1) crop rect for special="formula"


class PageGeometry(TypedDict):
    width: float
    height: float


class Paragraph(TypedDict, total=False):
    """A reflowed paragraph after noise stripping."""

    text: str
    page: int  # page where the paragraph starts
    font_size: float
    is_heading: bool  # any heading signal — used for rendering
    font_heading: bool  # oversized font only — eligible as an article boundary
    special: str  # "formula" | "table" — set on synthetic region paragraphs
    clip: tuple  # crop rect for special="formula"


class Article(TypedDict):
    index: int
    title: str
    subtitle: str  # empty string when the article has no standfirst
    paragraphs: list[str]
    headings: list[bool]  # parallel to paragraphs: crosshead/section heading?


class ArticleResult(TypedDict):
    title: str
    output_path: str
    n_paragraphs: int
    n_failed: int  # paragraphs left as [translation failed]
    mode: str  # "bilingual" | "chinese_only"
    pairs: list[dict]  # {"en", "zh", "failed"} — consumed by eval/, not CLI


class TokenUsage(TypedDict):
    node: str
    input_tokens: int
    output_tokens: int


class PipelineState(TypedDict, total=False):
    pdf_path: str
    style: str
    output_dir: str  # where .md files land; defaults to "outputs" (CLI)
    raw_blocks: list[Line]
    page_sizes: list[PageGeometry]
    cleaned_text: list[Paragraph]
    articles: list[Article]
    # Fan-in fields: article branches append via reducers.
    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]
    new_terms: Annotated[list[dict], operator.add]


class ArticleOutput(TypedDict, total=False):
    """What an article branch reports back to the parent graph. Restricted to
    reducer fields so parallel branches never collide on plain keys."""

    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]
    new_terms: Annotated[list[dict], operator.add]


class ArticleState(TypedDict, total=False):
    """Per-article sub-state carried through the Send fan-out branch."""

    style: str
    pdf_path: str
    output_dir: str
    article: Article
    has_english: bool
    script_state: str  # "none" | "simplified" | "traditional" | "mixed"
    english_paragraphs: list[str]  # source paragraphs, existing translation dropped
    english_headings: list[bool]  # parallel to english_paragraphs
    glossary: dict  # lowercased EN term -> glossary entry, for this style
    term_candidates: list[str]  # specialized terms not yet in the glossary
    resolved_terms: list[dict]  # researched entries awaiting glossary write
    translated_paragraphs: list[dict]  # {"en": str, "zh": str, "failed": bool}
    zh_title: str
    zh_subtitle: str
    output_mode: str  # "bilingual" (EN source) | "chinese_only" (ZH source)
    bilingual_md: str
    # Same reducer fields as the parent so subgraph output merges cleanly.
    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]
    new_terms: Annotated[list[dict], operator.add]
