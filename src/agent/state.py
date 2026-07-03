"""State schemas for the pub2md-agent LangGraph pipeline."""

import operator
from typing import Annotated, TypedDict


class Line(TypedDict):
    """One text line extracted from the PDF, with layout coordinates."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font_size: float


class PageGeometry(TypedDict):
    width: float
    height: float


class Paragraph(TypedDict):
    """A reflowed paragraph after noise stripping."""

    text: str
    page: int  # page where the paragraph starts
    font_size: float
    is_heading: bool


class Article(TypedDict):
    index: int
    title: str
    subtitle: str  # empty string when the article has no standfirst
    paragraphs: list[str]


class ArticleResult(TypedDict):
    title: str
    output_path: str
    n_paragraphs: int
    n_failed: int  # paragraphs left as [translation failed]


class TokenUsage(TypedDict):
    node: str
    input_tokens: int
    output_tokens: int


class PipelineState(TypedDict, total=False):
    pdf_path: str
    style: str
    raw_blocks: list[Line]
    page_sizes: list[PageGeometry]
    cleaned_text: list[Paragraph]
    articles: list[Article]
    # Fan-in fields: article branches append via reducers.
    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]


class ArticleOutput(TypedDict, total=False):
    """What an article branch reports back to the parent graph. Restricted to
    reducer fields so parallel branches never collide on plain keys."""

    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]


class ArticleState(TypedDict, total=False):
    """Per-article sub-state carried through the Send fan-out branch."""

    style: str
    pdf_path: str
    article: Article
    has_english: bool
    script_state: str  # "none" | "simplified" | "traditional" | "mixed"
    english_paragraphs: list[str]  # source paragraphs, existing translation dropped
    translated_paragraphs: list[dict]  # {"en": str, "zh": str, "failed": bool}
    zh_title: str
    zh_subtitle: str
    output_mode: str  # "bilingual" (EN source) | "chinese_only" (ZH source)
    bilingual_md: str
    # Same reducer fields as the parent so subgraph output merges cleanly.
    results: Annotated[list[ArticleResult], operator.add]
    errors: Annotated[list[str], operator.add]
    token_usage: Annotated[list[TokenUsage], operator.add]
