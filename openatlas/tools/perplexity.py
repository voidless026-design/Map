"""PerplexityEngine (pplxE) - keyless web/image search (DuckDuckGo + optional Ollama).

Replaces Perplexity's paid search. Text search uses DuckDuckGo via ``ddgs`` and can
be summarised by a local Ollama model when available; otherwise raw results are
returned. Image search returns DuckDuckGo image result URLs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.llm import ollama_client
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.search")


def _ddgs():
    try:
        from ddgs import DDGS  # newer package name

        return DDGS()
    except Exception:
        try:
            from duckduckgo_search import DDGS  # older package name

            return DDGS()
        except Exception as exc:  # pragma: no cover
            log.debug("ddgs unavailable: %s", exc)
            return None


@ToolRegistry.register("web-search")
class PerplexityEngine(BaseTool):
    abbrev = "pplxE"
    description = "Keyless web/image search via DuckDuckGo, optionally summarised by Ollama."

    specs = {
        "search_perplexity_text": ToolSpec(
            name="search_perplexity_text",
            description="Search the web (DuckDuckGo) and optionally summarise with a local LLM.",
            parameters={"search_request": {"type": "string", "required": True,
                                           "description": "Query string"}},
            backend="DuckDuckGo (+Ollama)", network=True, needs_llm=False,
        ),
        "search_perplexity_images": ToolSpec(
            name="search_perplexity_images",
            description="Search for images via DuckDuckGo and return result URLs.",
            parameters={"search_request": {"type": "string", "required": True,
                                           "description": "Image query string"}},
            backend="DuckDuckGo", network=True,
        ),
    }

    @staticmethod
    def search_perplexity_text(search_request: str) -> ToolResult:
        ddgs = _ddgs()
        if ddgs is None:
            return ToolResult.unavailable(
                "search_perplexity_text", "ddgs not installed (poetry install --with search)"
            )
        results: List[Dict[str, Any]] = []
        try:
            for r in ddgs.text(search_request, max_results=10):
                results.append({"title": r.get("title"), "href": r.get("href"),
                                "body": r.get("body")})
        except Exception as exc:
            return ToolResult.unavailable("search_perplexity_text", f"search failed: {exc}")

        summary = None
        if results and ollama_client.available():
            joined = "\n".join(f"- {r['title']}: {r['body']} ({r['href']})" for r in results)
            summary = ollama_client.complete(
                f"Summarise these search results for the query '{search_request}', "
                f"citing sources by URL:\n{joined}",
                system="You are a concise OSINT research assistant.",
            )
        return ToolResult(
            tool_name="search_perplexity_text",
            content={"query": search_request, "results": results, "summary": summary},
            success=True,
            metadata={"summarised_by": "ollama" if summary else "none"},
        )

    @staticmethod
    def search_perplexity_images(search_request: str) -> ToolResult:
        ddgs = _ddgs()
        if ddgs is None:
            return ToolResult.unavailable("search_perplexity_images", "ddgs not installed")
        images: List[Dict[str, Any]] = []
        try:
            for r in ddgs.images(search_request, max_results=10):
                images.append({"title": r.get("title"), "image": r.get("image"),
                               "url": r.get("url"), "source": r.get("source")})
        except Exception as exc:
            return ToolResult.unavailable("search_perplexity_images", f"search failed: {exc}")
        return ToolResult(tool_name="search_perplexity_images",
                          content={"query": search_request, "images": images}, success=True)
