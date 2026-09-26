"""Wikipedia + Wikidata lookups (public figures, organisations, places) - keyless."""

from __future__ import annotations

import re

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net

WP_API = "https://en.wikipedia.org/w/api.php"
WD_API = "https://www.wikidata.org/w/api.php"


def _clean(html_snippet: str) -> str:
    return re.sub(r"<[^>]+>", "", html_snippet or "").replace("&quot;", '"')


@source("wikipedia", title="Wikipedia & Wikidata", filters=("people", "web"),
        description="Encyclopedia articles and Wikidata entities for public figures/orgs",
        applies_to=("name", "domain", "username"))
async def wikipedia(t: Target, net: Net) -> SourceResult:
    res = SourceResult("wikipedia", ok=True, searched=f"Wikipedia/Wikidata for '{t.value}'")
    wp = await net.get_json(WP_API, params={"action": "query", "list": "search", "format": "json",
                                            "srsearch": f'"{t.value}"', "srlimit": 3})
    for hit in (wp or {}).get("query", {}).get("search", []):
        title = hit.get("title", "")
        exact = title.lower() == t.value.lower()
        res.evidence.append(Evidence(
            source="wikipedia", kind="mention", title=f"Wikipedia: {title}",
            url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
            snippet=_clean(hit.get("snippet", "")), confidence=0.7 if exact else 0.4,
            data={"exact_title": exact}))
    wd = await net.get_json(WD_API, params={"action": "wbsearchentities", "format": "json",
                                            "language": "en", "search": t.value, "limit": 3})
    for e in (wd or {}).get("search", []):
        res.evidence.append(Evidence(
            source="wikidata", kind="record",
            title=f"Wikidata {e.get('id')}: {e.get('label', '')}",
            url=e.get("concepturi") or f"https://www.wikidata.org/wiki/{e.get('id')}",
            snippet=e.get("description", ""),
            confidence=0.6 if (e.get("label") or "").lower() == t.value.lower() else 0.35))
    if wp is None and wd is None:
        res.ok, res.error = False, "Wikipedia/Wikidata unreachable"
    return res
