"""HyperlinkExtractEngine (HLE) - extract hyperlinks from public pages (robots-gated)."""

from __future__ import annotations

import re
import urllib.parse
from typing import List

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import scrape_get

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _extract(html: str, base: str) -> List[str]:
    links = []
    for raw in _HREF_RE.findall(html or ""):
        if raw.startswith(("mailto:", "tel:")):
            links.append(raw)
        else:
            links.append(urllib.parse.urljoin(base, raw))
    # de-dup, preserve order
    seen, out = set(), []
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


@ToolRegistry.register("hyperlink-extract")
class HyperlinkExtractEngine(BaseTool):
    abbrev = "HLE"
    description = "Extract hyperlinks (incl. mailto/social) from public web pages."

    specs = {
        "hyperlinks_for_single_url": ToolSpec(
            name="hyperlinks_for_single_url",
            description="Extract all hyperlinks from a single public page (robots-gated).",
            parameters={"url": {"type": "string", "required": True, "description": "Page URL"}},
            network=True, scrapes_web=True,
        ),
        "hyperlinks_for_multiple_urls": ToolSpec(
            name="hyperlinks_for_multiple_urls",
            description="Extract hyperlinks from several public pages (robots-gated).",
            parameters={"urls": {"type": "array", "required": True, "description": "List of URLs"}},
            network=True, scrapes_web=True,
        ),
    }

    @staticmethod
    def hyperlinks_for_single_url(url: str) -> ToolResult:
        resp = scrape_get(url)
        if resp is None or resp.status_code != 200:
            return ToolResult(
                tool_name="hyperlinks_for_single_url",
                content={"url": url, "links": []}, success=False,
                error="robots-disallowed or request failed",
            )
        return ToolResult(
            tool_name="hyperlinks_for_single_url",
            content={"url": url, "links": _extract(resp.text, url)}, success=True,
        )

    @staticmethod
    def hyperlinks_for_multiple_urls(urls) -> ToolResult:
        if isinstance(urls, str):
            urls = [u.strip() for u in urls.split(",") if u.strip()]
        out = {}
        for u in urls or []:
            r = HyperlinkExtractEngine.hyperlinks_for_single_url(u)
            out[u] = r.content.get("links", [])
        return ToolResult(tool_name="hyperlinks_for_multiple_urls", content=out, success=bool(out))
