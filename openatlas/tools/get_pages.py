"""GetPagesEngine (GPE) - robots-gated HTTP GET of public URLs."""

from __future__ import annotations

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import scrape_get


@ToolRegistry.register("get-pages")
class GetPagesEngine(BaseTool):
    abbrev = "GPE"
    description = "Robots-gated HTTP GET of one or many public URLs."

    specs = {
        "fetch_get_page": ToolSpec(
            name="fetch_get_page",
            description="Fetch a single public URL (robots-gated) and return status + text.",
            parameters={"url": {"type": "string", "required": True, "description": "Full URL"}},
            network=True, scrapes_web=True,
        ),
        "fetch_get_pages_bulk": ToolSpec(
            name="fetch_get_pages_bulk",
            description="Fetch multiple public URLs (robots-gated), comma-separated.",
            parameters={"urls": {"type": "string", "required": True, "description": "Comma-separated URLs"}},
            network=True, scrapes_web=True,
        ),
    }

    @staticmethod
    def fetch_get_page(url: str) -> ToolResult:
        resp = scrape_get(url)
        if resp is None:
            return ToolResult(
                tool_name="fetch_get_page",
                content={"url": url, "status": -1, "text": "", "reason": "disallowed or unreachable"},
                success=False, error="robots-disallowed or request failed",
            )
        body = resp.text or ""
        # The fetch itself succeeded; the HTTP status is reported in content.
        return ToolResult(
            tool_name="fetch_get_page",
            content={"url": url, "status": resp.status_code, "text": body[:20000],
                     "truncated": len(body) > 20000},
            success=True,
        )

    @staticmethod
    def fetch_get_pages_bulk(urls: str) -> ToolResult:
        targets = [u.strip() for u in (urls or "").split(",") if u.strip()]
        if not targets:
            return ToolResult.failure("fetch_get_pages_bulk", "no URLs provided")
        out = {}
        for u in targets:
            r = GetPagesEngine.fetch_get_page(u)
            out[u] = r.content
        return ToolResult(tool_name="fetch_get_pages_bulk", content=out, success=True)
