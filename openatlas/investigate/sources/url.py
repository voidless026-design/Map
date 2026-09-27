"""Read a public web page: title, description, outbound social profiles and emails."""

from __future__ import annotations

import urllib.parse

from openatlas.investigate import extract
from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("page-read", title="Read the web page", filters=("web",),
        description="Fetches the page (robots.txt-respecting) and lists linked profiles and emails",
        applies_to=("url",))
async def page_read(t: Target, net: Net) -> SourceResult:
    r = await net.get(t.value, page=True)
    res = SourceResult("page-read", ok=r.ok, searched=f"page {t.value}")
    if not r.ok:
        res.error = r.error or f"HTTP {r.status_code}"
        return res
    title, text, links = extract.page_text(r.text)
    res.evidence.append(Evidence(
        source="page-read", kind="record", title=f"Page title: {title or '(none)'}", url=r.url,
        snippet=text[:300], confidence=0.9, verified=True,
        verification={"method": "fetched live"}))
    seen = set()
    for href in links:
        full = urllib.parse.urljoin(r.url, href)
        prof = extract.social_profile(full)
        if prof and prof["url"] not in seen:
            seen.add(prof["url"])
            res.evidence.append(Evidence(
                source="page-read", kind="entity", title=f"Links to {prof['site']} profile @{prof['handle']}",
                url=prof["url"], snippet=f"linked from {r.url}", entity_type="username",
                entity_value=prof["handle"].lower(), confidence=0.7, verified=True,
                verification={"method": "link present on fetched page"}))
        if href.startswith("mailto:"):
            email = href[7:].split("?")[0].lower()
            if email and email not in seen:
                seen.add(email)
                res.evidence.append(Evidence(
                    source="page-read", kind="entity", title=f"Email on page: {email}", url=r.url,
                    snippet=f"mailto link on {r.url}", entity_type="email", entity_value=email,
                    confidence=0.75, verified=True, verification={"method": "present on fetched page"}))
    return res
