"""Reddit public JSON (no login). Reddit may rate-limit anonymous requests."""

from __future__ import annotations

import datetime as _dt

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("reddit", title="Reddit", filters=("people", "username"),
        description="Reddit account (by username) or public posts mentioning the target",
        applies_to=("username", "name", "email"))
async def reddit(t: Target, net: Net) -> SourceResult:
    if t.type == "username":
        r = await net.get(f"https://www.reddit.com/user/{t.value}/about.json")
        res = SourceResult("reddit", ok=r.status_code in (200, 404),
                           searched=f"Reddit user u/{t.value}")
        if r.status_code in (403, 429) or r.error:
            res.ok, res.error = False, f"Reddit refused anonymous access (HTTP {r.status_code})"
        data = r.json() if r.ok else None
        d = (data or {}).get("data") or {}
        if d.get("name"):
            created = d.get("created_utc")
            since = _dt.datetime.fromtimestamp(created, _dt.timezone.utc).date().isoformat() \
                if created else "?"
            res.evidence.append(Evidence(
                source="reddit", kind="account", title=f"Reddit: u/{d['name']}",
                url=f"https://www.reddit.com/user/{d['name']}",
                snippet=f"account since {since}; karma {d.get('total_karma', '?')}",
                entity_type="username", entity_value=d["name"], confidence=0.8, verified=True,
                verification={"method": "first-party API"}, data={"created": since}))
        return res
    data = await net.get_json("https://www.reddit.com/search.json",
                              params={"q": f'"{t.value}"', "limit": 10, "sort": "relevance"})
    res = SourceResult("reddit", ok=data is not None, searched=f"Reddit posts mentioning '{t.value}'")
    if data is None:
        res.error = "Reddit refused anonymous access or is unreachable"
    for c in (data or {}).get("data", {}).get("children", []):
        p = c.get("data", {})
        res.evidence.append(Evidence(
            source="reddit", kind="mention", title=f"r/{p.get('subreddit')}: {p.get('title', '')}"[:160],
            url="https://www.reddit.com" + p.get("permalink", ""),
            snippet=(p.get("selftext") or "")[:300], confidence=0.35,
            data={"author": p.get("author")}))
    return res
