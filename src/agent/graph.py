"""LangGraph graph assembly.

Main pipeline: pdf_extractor → noise_stripper → article_segmenter, then a
Send fan-out runs one per-article subgraph per detected article:

    lang_state_detector
      ├─(has_english)→ en_text_isolator → domain_glossary_loader
      │      → term_candidate_extractor ─┬─(candidates)→ term_verifier
      │                                  │    ─┬─(verified)→ term_researcher
      │                                  │     │              → glossary_updater ─┐
      │                                  └─(none)──────────────────────────────────┤
      │                                                          → translator ┤
      └─(chinese)→ opencc_converter ──────────────────────────────────────────┤
                                                                               ↓
                                                          formatter → output_writer

Article branches merge their results, errors, token usage and new glossary
terms back into the parent state via list reducers.
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.agent.nodes.article_segmenter import article_segmenter
from src.agent.nodes.domain_glossary_loader import domain_glossary_loader
from src.agent.nodes.en_text_isolator import en_text_isolator
from src.agent.nodes.formatter import formatter
from src.agent.nodes.formula_transcriber import formula_transcriber
from src.agent.nodes.glossary_updater import glossary_updater
from src.agent.nodes.lang_state_detector import lang_state_detector
from src.agent.nodes.noise_stripper import noise_stripper
from src.agent.nodes.opencc_converter import opencc_converter
from src.agent.nodes.output_writer import output_writer
from src.agent.nodes.pdf_extractor import pdf_extractor
from src.agent.nodes.term_candidate_extractor import term_candidate_extractor
from src.agent.nodes.term_researcher import term_researcher
from src.agent.nodes.term_verifier import term_verifier
from src.agent.nodes.translator import translator
from src.agent.state import ArticleOutput, ArticleState, PipelineState


def _fan_out(state: PipelineState) -> list[Send]:
    return [
        Send(
            "process_article",
            ArticleState(
                base_style=state["base_style"],
                domains=state["domains"],
                pdf_path=state["pdf_path"],
                output_dir=state.get("output_dir", ""),
                article=article,
            ),
        )
        for article in state["articles"]
    ]


def _build_article_subgraph():
    # output_schema keeps branch-local keys (style, article, ...) from being
    # written back to the parent, where parallel branches would collide.
    sub = StateGraph(ArticleState, output_schema=ArticleOutput)
    sub.add_node("lang_state_detector", lang_state_detector)
    sub.add_node("en_text_isolator", en_text_isolator)
    sub.add_node("domain_glossary_loader", domain_glossary_loader)
    sub.add_node("term_candidate_extractor", term_candidate_extractor)
    sub.add_node("term_verifier", term_verifier)
    sub.add_node("term_researcher", term_researcher)
    sub.add_node("glossary_updater", glossary_updater)
    sub.add_node("opencc_converter", opencc_converter)
    sub.add_node("translator", translator)
    sub.add_node("formatter", formatter)
    sub.add_node("output_writer", output_writer)

    sub.add_edge(START, "lang_state_detector")
    sub.add_conditional_edges(
        "lang_state_detector",
        lambda s: "en_text_isolator" if s["has_english"] else "opencc_converter",
        ["en_text_isolator", "opencc_converter"],
    )
    sub.add_edge("en_text_isolator", "domain_glossary_loader")
    sub.add_edge("domain_glossary_loader", "term_candidate_extractor")
    sub.add_conditional_edges(
        "term_candidate_extractor",
        lambda s: "term_verifier" if s.get("term_candidates") else "translator",
        ["term_verifier", "translator"],
    )
    sub.add_conditional_edges(
        "term_verifier",
        lambda s: "term_researcher" if s.get("term_candidates") else "translator",
        ["term_researcher", "translator"],
    )
    sub.add_edge("term_researcher", "glossary_updater")
    sub.add_edge("glossary_updater", "translator")
    sub.add_edge("translator", "formatter")
    sub.add_edge("opencc_converter", "formatter")
    sub.add_edge("formatter", "output_writer")
    sub.add_edge("output_writer", END)
    return sub.compile()


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("pdf_extractor", pdf_extractor)
    graph.add_node("noise_stripper", noise_stripper)
    graph.add_node("formula_transcriber", formula_transcriber)
    graph.add_node("article_segmenter", article_segmenter)
    graph.add_node("process_article", _build_article_subgraph())

    graph.add_edge(START, "pdf_extractor")
    graph.add_edge("pdf_extractor", "noise_stripper")
    graph.add_edge("noise_stripper", "formula_transcriber")
    graph.add_edge("formula_transcriber", "article_segmenter")
    graph.add_conditional_edges("article_segmenter", _fan_out, ["process_article"])
    graph.add_edge("process_article", END)
    return graph.compile()
