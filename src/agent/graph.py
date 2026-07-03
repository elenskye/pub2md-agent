"""LangGraph graph assembly.

Main pipeline: pdf_extractor → noise_stripper → article_segmenter, then a
Send fan-out runs one per-article subgraph (translator → formatter →
output_writer) per detected article. Article branches merge their results,
errors and token usage back into the parent state via list reducers.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agent.nodes.article_segmenter import article_segmenter
from src.agent.nodes.formatter import formatter
from src.agent.nodes.noise_stripper import noise_stripper
from src.agent.nodes.output_writer import output_writer
from src.agent.nodes.pdf_extractor import pdf_extractor
from src.agent.nodes.translator import translator
from src.agent.state import ArticleOutput, ArticleState, PipelineState


def _fan_out(state: PipelineState) -> list[Send]:
    return [
        Send(
            "process_article",
            ArticleState(style=state["style"], pdf_path=state["pdf_path"], article=article),
        )
        for article in state["articles"]
    ]


def _build_article_subgraph():
    # output_schema keeps branch-local keys (style, article, ...) from being
    # written back to the parent, where parallel branches would collide.
    sub = StateGraph(ArticleState, output_schema=ArticleOutput)
    sub.add_node("translator", translator)
    sub.add_node("formatter", formatter)
    sub.add_node("output_writer", output_writer)
    sub.add_edge(START, "translator")
    sub.add_edge("translator", "formatter")
    sub.add_edge("formatter", "output_writer")
    sub.add_edge("output_writer", END)
    return sub.compile()


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("pdf_extractor", pdf_extractor)
    graph.add_node("noise_stripper", noise_stripper)
    graph.add_node("article_segmenter", article_segmenter)
    graph.add_node("process_article", _build_article_subgraph())

    graph.add_edge(START, "pdf_extractor")
    graph.add_edge("pdf_extractor", "noise_stripper")
    graph.add_edge("noise_stripper", "article_segmenter")
    graph.add_conditional_edges("article_segmenter", _fan_out, ["process_article"])
    graph.add_edge("process_article", END)
    return graph.compile()
