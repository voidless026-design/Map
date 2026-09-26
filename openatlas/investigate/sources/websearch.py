"""Web search with targeted queries ("dorks"), keyless.

Backends: a self-hosted **SearXNG** instance if ``OPENATLAS_SEARXNG_URL`` is set (free,
open source, avoids rate limits), otherwise **DuckDuckGo** via the ``ddgs`` package.
Results are evidence of a *mention*; the pipeline then opens the top pages to confirm
the target really appears there.
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net

RESULTS_PER_QUERY = 8
MAX_QUERIES = 4


def dorks(t: Target) -> List[str]:
    v = t.value
    if t.type == "name":
        q = [f'"{v}"',
             f'"{v}" (site:github.com OR site:gitlab.com OR site:stackoverflow.com)',
             f'"{v}" site:linkedin.com/in',
             f'"{v}" (site:x.com OR site:twitter.com OR site:bsky.app OR site:mastodon.social)',
             f'"{v}" (resume OR cv OR "about me" OR portfolio)']
    elif t.type == "username":
        q = [f'"{v}"', f'"{v}" (profile OR user OR account)', f"inurl:{v}"]
    elif t.type == "email":
        local, _, domain = v.partition("@")
        q = [f'"{v}"', f'"{local}" "{domain}"']
    elif t.type == "phone":
        q = [f'"{x}"' for x in _phone_formats(v)]
    elif t.type == "domain":
        q = [f"site:{v}", f'"{v}" -site:{v}']
    elif t.type == "url":
        q = [f'"{v}"']
    else:
        q = [f'"{v}"']
    return q[:MAX_QUERIES]


def _phone_formats(v: str) -> List[str]:
    try:
        import phonenumbers

        n = phonenumbers.parse(v, os.getenv("OPENATLAS_DEFAULT_REGION", "US"))
        fmts = [phonenumbers.format_number(n, f) for f in (
            phonenumbers.PhoneNumberFormat.E164, phonenumbers.PhoneNumberFormat.INTERNATIONAL,
            phonenumbers.PhoneNumberFormat.NATIONAL)]
        return list(dict.fromkeys(fmts))
    except Exception:
        return [v]


def _ddg(query: str, n: int) -> List[Dict[str, str]]:
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:
        from duckduckgo_search import DDGS  # type: ignore
    return [{"title": r.get("title", ""), "url": r.get("href") or r.get("url", ""),
             "snippet": r.get("body", "")} for r in DDGS().text(query, max_results=n)]


async def _searxng(net: Net, base: str, query: str, n: int) -> List[Dict[str, str]]:
    data = await net.get_json(base.rstrip("/") + "/search",
                              params={"q": query, "format": "json"})
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in (data or {}).get("results", [])[:n]]


def backend() -> str:
    return "searxng" if os.getenv("OPENATLAS_SEARXNG_URL") else "duckduckgo"


@source("web-search", title="Web search", filters=("people", "username", "email", "phone", "web"),
        description="Targeted search-engine queries (dorks) for public mentions",
        applies_to=("name", "username", "email", "phone", "domain", "url"), timeout=60)
async def web_search(t: Target, net: Net) -> SourceResult:
    queries = dorks(t)
    engine = backend()
    res = SourceResult("web-search", ok=True,
                       searched=f"{engine}: " + " | ".join(queries))
    seen = set()
    errors = []
    needle = t.value.lower()
    for i, q in enumerate(queries):
        try:
            if engine == "searxng":
                hits = await _searxng(net, os.environ["OPENATLAS_SEARXNG_URL"], q, RESULTS_PER_QUERY)
            else:
                hits = await asyncio.to_thread(_ddg, q, RESULTS_PER_QUERY)
        except Exception as exc:  # rate limit / no package / network
            errors.append(f"{q}: {type(exc).__name__}: {exc}")
            continue
        for h in hits:
            url = h.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            text = f"{h.get('title', '')} {h.get('snippet', '')}".lower()
            exact = needle in text
            res.evidence.append(Evidence(
                source="web-search", kind="mention", title=h.get("title") or url, url=url,
                snippet=h.get("snippet", ""), confidence=0.6 if exact else 0.35,
                data={"query": q, "engine": engine, "exact_match_in_snippet": exact},
            ))
        if i < len(queries) - 1 and engine == "duckduckgo":
            await asyncio.sleep(1.0)  # be polite; DuckDuckGo throttles bursts
    if errors and not res.evidence:
        res.ok, res.error = False, "; ".join(errors)[:500]
    return res
