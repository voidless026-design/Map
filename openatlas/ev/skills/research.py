"""Research Synthesis: search the brain (and, with your approval, the public web), then answer
from what was found with numbered citations. The Quality Assurance skill checks the answer."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

from openatlas.ev.tools import tool


@tool("search_brain", kind="read", skill="Research Synthesis",
      description="Search E.V's local knowledge base (the brain: Wikipedia, Kiwix books, past cases). "
                  "Returns on-topic passages with why each matched.",
      params={"query": {"type": "string"}, "k": {"type": "integer", "description": "max results (default 5)"}},
      required=["query"])
def search_brain(query: str, k: int = 5) -> Dict[str, Any]:
    from openatlas.kb import retrieve

    hits = retrieve.search(query, k=max(1, min(int(k or 5), 10)))
    return {"query": query, "found": len(hits),
            "sources": [{"title": h["title"], "url": h.get("url") or "", "text": (h.get("text") or h.get("snippet") or "")[:900],
                         "why": h.get("why", ""), "license": h.get("license", "")} for h in hits]}


@tool("read_article", kind="read", skill="Research Synthesis",
      description="Read the full stored text of one brain article by its title.",
      params={"title": {"type": "string"}}, required=["title"])
def read_article(title: str) -> Dict[str, Any]:
    from openatlas.kb import store

    with store.connect() as con:
        row = con.execute("SELECT d.id, d.title, d.url, d.license FROM documents d WHERE lower(d.title)=lower(?) "
                          "LIMIT 1", (title,)).fetchone()
        if not row:
            return {"ok": False, "error": f"the brain has no article titled '{title}'"}
        chunks = con.execute("SELECT text FROM chunks WHERE doc_id=? ORDER BY ord LIMIT 12", (row["id"],)).fetchall()
    text = "\n".join(c["text"] for c in chunks)
    return {"title": row["title"], "url": row["url"], "license": row["license"],
            "sources": [{"title": row["title"], "url": row["url"] or "", "text": text[:6000]}]}


@tool("web_search", kind="network", skill="Research Synthesis",
      description="Search the public web (DuckDuckGo or your SearXNG) for current information. Needs approval.",
      params={"query": {"type": "string"}, "n": {"type": "integer", "description": "results (default 6)"}},
      required=["query"])
def web_search(query: str, n: int = 6) -> Dict[str, Any]:
    from openatlas.investigate.sources import websearch

    n = max(1, min(int(n or 6), 10))
    base = os.getenv("OPENATLAS_SEARXNG_URL")
    if base:
        from openatlas.net.client import Net

        async def go():
            async with Net() as net:
                return await websearch._searxng(net, base, query, n)
        results = asyncio.run(go())
    else:
        results = websearch._ddg(query, n)
    return {"query": query, "found": len(results),
            "sources": [{"title": r["title"], "url": r["url"], "text": r["snippet"]} for r in results]}
