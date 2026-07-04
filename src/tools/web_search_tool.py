"""Tavily web search wrapper for terminology research.

Results are trimmed hard before they reach any LLM context (spec 4.1.3):
only the top few snippets, each capped in length.
"""

from src.config import load_settings

_MAX_RESULTS = 3
_SNIPPET_CHARS = 240


class SearchUnavailableError(RuntimeError):
    """Search failed or is unconfigured; caller should fall back to the LLM."""


def search_term(query: str) -> str:
    """Run a web search and return a compact snippet digest for LLM use."""
    settings = load_settings()
    if not settings.tavily_api_key:
        raise SearchUnavailableError("TAVILY_API_KEY is not set")
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(query, max_results=_MAX_RESULTS, search_depth="basic")
        results = response.get("results", [])
    except Exception as exc:
        raise SearchUnavailableError(f"Tavily search failed: {exc}") from exc

    snippets = [
        f"- {r.get('title', '')}: {r.get('content', '')[:_SNIPPET_CHARS]}"
        for r in results
        if r.get("content")
    ]
    if not snippets:
        raise SearchUnavailableError(f"no usable search results for: {query}")
    return "\n".join(snippets)
