"""Open the top search-result pages and check what they actually say.

This is what turns "a search engine returned a link" into evidence: the page is fetched
(robots.txt respected, data brokers skipped), the target is looked for in the real text,
and nearby emails / phones / profile links are extracted with their context.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import List, Tuple

from openatlas.investigate import extract
from openatlas.investigate.models import Evidence, Target
from openatlas.net.client import Net, is_data_broker


def needles(t: Target) -> List[str]:
    return [t.value] + [v for v in t.variants if len(v) >= 3]


def pick_pages(evidence: List[Evidence], limit: int) -> List[Evidence]:
    """Highest-confidence search mentions, one per host, no data brokers."""
    hosts, out = set(), []
    for ev in sorted(evidence, key=lambda e: -e.confidence):
        if ev.source != "web-search" or not ev.url or is_data_broker(ev.url):
            continue
        host = urllib.parse.urlsplit(ev.url).hostname or ""
        if host in hosts:
            continue
        hosts.add(host)
        out.append(ev)
        if len(out) >= limit:
            break
    return out


async def read_page(net: Net, t: Target, ev: Evidence) -> Tuple[Evidence, List[Evidence]]:
    """Fetch ``ev.url``; set its verification; return new entity evidence found on it."""
    r = await net.get(ev.url, page=True, max_bytes=1024 * 1024)
    if not r.ok:
        ev.verification = {"method": "open the page", "result": "could not open",
                           "reason": r.error or f"HTTP {r.status_code}"}
        return ev, []
    title, text, links = extract.page_text(r.text)
    spans = extract.find_mentions(text, needles(t))
    if spans:
        ev.verified = True
        ev.confidence = min(0.9, ev.confidence + 0.25)
        ev.snippet = extract.context(text, *spans[0])
        ev.verification = {"method": "opened the page", "result": "target text found on page",
                           "mentions": len(spans)}
    else:
        ev.verified = False
        ev.confidence = max(0.05, ev.confidence - 0.25)
        ev.verification = {"method": "opened the page",
                           "result": "target not found on the live page (stale or loose match)"}
        return ev, []
    found: List[Evidence] = []
    for ent in extract.entities_near(text, needles(t)):
        if ent["value"].lower() == t.value.lower():
            continue
        found.append(Evidence(
            source="page-reader", kind="entity",
            title=f"{ent['type']} near the target on {urllib.parse.urlsplit(r.url).hostname}: {ent['value']}",
            url=r.url, snippet=ent["snippet"], entity_type=ent["type"],
            entity_value=ent["value"].lower(), confidence=0.4, verified=True,
            verification={"method": "present on fetched page",
                          "note": "appears near the target; attribution not proven"}))
    for href in links:
        prof = extract.social_profile(urllib.parse.urljoin(r.url, href))
        if prof and any(n.lower().replace(" ", "") in prof["handle"].lower() for n in needles(t)):
            found.append(Evidence(
                source="page-reader", kind="entity",
                title=f"Page links a {prof['site']} profile @{prof['handle']}", url=prof["url"],
                snippet=f"linked from {r.url}", entity_type="username",
                entity_value=prof["handle"].lower(), confidence=0.5, verified=True,
                verification={"method": "link present on fetched page"}))
    return ev, found


async def read_pages(net: Net, t: Target, evidence: List[Evidence], limit: int = 6) -> List[Evidence]:
    picked = pick_pages(evidence, limit)
    results = await asyncio.gather(*(read_page(net, t, ev) for ev in picked))
    return [e for _, new in results for e in new]
