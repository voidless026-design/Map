"""MediaWiki API client for the brain (keyless, polite).

Follows Wikimedia API etiquette: requests are serial (one at a time), rate-limited,
identify the client with a contactable User-Agent, send ``maxlag=5`` and back off when
the servers are lagged. Text comes from the TextExtracts plain-text API; every article
keeps its revision id and CC BY-SA 4.0 attribution.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from openatlas.net.client import Net

API = "https://en.wikipedia.org/w/api.php"
LICENSE = "CC BY-SA 4.0 (Wikipedia contributors)"


class Wiki:
    def __init__(self, net: Net, rate: float = 2.0):
        self.net = net
        self.min_gap = 1.0 / max(rate, 0.1)
        self._last = 0.0
        self.requests = 0

    async def _get(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        for attempt in range(4):
            gap = self.min_gap - (time.monotonic() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()
            self.requests += 1
            r = await self.net.get(API, params=params, max_bytes=8 * 1024 * 1024)
            if r.status_code == 429 or (r.ok and (r.json() or {}).get("error", {}).get("code") == "maxlag"):
                wait = float(r.headers.get("retry-after", 5)) * (attempt + 1)
                await asyncio.sleep(min(wait, 60))
                continue
            return r.json() if r.ok else None
        return None

    async def resolve(self, titles: List[str]) -> Dict[str, Dict[str, Any]]:
        """Map each input title -> {title, pageid, missing, disambiguation, revid} (50 per call)."""
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            data = await self._get({"action": "query", "titles": "|".join(batch), "redirects": "1",
                                    "prop": "pageprops|info", "ppprop": "disambiguation"})
            if not data:
                continue
            q = data.get("query", {})
            alias = {n["from"]: n["to"] for n in q.get("normalized", [])}
            alias.update({r["from"]: r["to"] for r in q.get("redirects", [])})
            pages = {p["title"]: p for p in q.get("pages", [])}
            for t in batch:
                final = t
                for _ in range(3):
                    final = alias.get(final, final)
                p = pages.get(final, {})
                out[t] = {"title": p.get("title", final), "pageid": p.get("pageid"),
                          "missing": bool(p.get("missing")) or not p,
                          "disambiguation": "disambiguation" in (p.get("pageprops") or {}),
                          "revid": p.get("lastrevid")}
        return out

    async def article(self, title: str) -> Optional[Dict[str, Any]]:
        """Plain text + metadata for one article (follows redirects)."""
        data = await self._get({"action": "query", "titles": title, "redirects": "1",
                                "prop": "extracts|info|pageprops", "explaintext": "1",
                                "exsectionformat": "wiki", "ppprop": "disambiguation"})
        pages = (data or {}).get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return None
        p = pages[0]
        return {"title": p["title"], "pageid": p.get("pageid"), "revid": p.get("lastrevid"),
                "text": p.get("extract") or "",
                "disambiguation": "disambiguation" in (p.get("pageprops") or {}),
                "url": "https://en.wikipedia.org/wiki/" + p["title"].replace(" ", "_")}

    async def category_members(self, category: str, limit: int = 500) -> List[Tuple[int, str]]:
        """(namespace, title) of pages (ns 0) and subcategories (ns 14) in a category."""
        if not category.startswith("Category:"):
            category = "Category:" + category
        out: List[Tuple[int, str]] = []
        cont: Dict[str, str] = {}
        while len(out) < limit:
            data = await self._get({"action": "query", "list": "categorymembers", "cmtitle": category,
                                    "cmnamespace": "0|14", "cmlimit": str(min(500, limit)), **cont})
            if not data:
                break
            out += [(m["ns"], m["title"]) for m in data.get("query", {}).get("categorymembers", [])]
            if "continue" not in data:
                break
            cont = {k: v for k, v in data["continue"].items() if k != "continue"}
        return out[:limit]

    async def vital_articles(self, level: int = 4) -> List[str]:
        """All article titles linked from Wikipedia:Vital articles/Level/<level>/* subpages."""
        prefix = f"Vital articles/Level/{level}/"
        pages, cont = [], {}
        while True:
            data = await self._get({"action": "query", "list": "allpages", "apnamespace": "4",
                                    "apprefix": prefix, "aplimit": "500", **cont})
            if not data:
                break
            pages += [p["title"] for p in data.get("query", {}).get("allpages", [])]
            if "continue" not in data:
                break
            cont = {k: v for k, v in data["continue"].items() if k != "continue"}
        titles: List[str] = []
        for page in pages:
            cont = {}
            while True:
                data = await self._get({"action": "query", "titles": page, "prop": "links",
                                        "plnamespace": "0", "pllimit": "max", **cont})
                if not data:
                    break
                for p in data.get("query", {}).get("pages", []):
                    titles += [link["title"] for link in p.get("links", [])]
                if "continue" not in data:
                    break
                cont = {k: v for k, v in data["continue"].items() if k != "continue"}
        return list(dict.fromkeys(titles))
