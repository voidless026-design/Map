"""Hacker News: official Firebase API (users) + Algolia search API. Keyless."""

from __future__ import annotations

import datetime as _dt
import re

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("hackernews", title="Hacker News", filters=("people", "username", "code"),
        description="HN account (by username) and stories/comments mentioning the target",
        applies_to=("username", "name", "email", "domain"))
async def hackernews(t: Target, net: Net) -> SourceResult:
    res = SourceResult("hackernews", ok=True, searched=f"Hacker News for '{t.value}'")
    if t.type == "username":
        u = await net.get_json(f"https://hacker-news.firebaseio.com/v0/user/{t.value}.json")
        if u and u.get("id"):
            since = _dt.datetime.fromtimestamp(u.get("created", 0), _dt.timezone.utc).date()
            about = re.sub(r"<[^>]+>", " ", u.get("about") or "")[:300]
            res.evidence.append(Evidence(
                source="hackernews", kind="account", title=f"Hacker News: {u['id']}",
                url=f"https://news.ycombinator.com/user?id={u['id']}",
                snippet=f"karma {u.get('karma')}, since {since}. {about}".strip(),
                entity_type="username", entity_value=u["id"], confidence=0.8, verified=True,
                verification={"method": "first-party API"}))
    data = await net.get_json("https://hn.algolia.com/api/v1/search",
                              params={"query": f'"{t.value}"', "hitsPerPage": 8})
    if data is None and not res.evidence:
        res.ok, res.error = False, "Hacker News APIs unreachable"
    for h in (data or {}).get("hits", []):
        text = re.sub(r"<[^>]+>", " ", h.get("comment_text") or h.get("story_text") or "")[:300]
        res.evidence.append(Evidence(
            source="hackernews", kind="mention",
            title=h.get("title") or f"comment by {h.get('author')}",
            url=f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            snippet=text, confidence=0.35, data={"author": h.get("author")}))
    return res
