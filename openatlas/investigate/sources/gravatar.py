"""Gravatar public profile for an email (looked up by hash - the email is never sent)."""

from __future__ import annotations

import hashlib

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("gravatar", title="Gravatar profile", filters=("email", "people"),
        description="Public Gravatar profile tied to the email (lookup by hash)",
        applies_to=("email",))
async def gravatar(t: Target, net: Net) -> SourceResult:
    email = t.value.strip().lower()
    sha = hashlib.sha256(email.encode()).hexdigest()
    md5 = hashlib.md5(email.encode()).hexdigest()  # noqa: S324 - Gravatar's legacy id format
    res = SourceResult("gravatar", ok=True, searched="Gravatar profile by email hash")
    prof = await net.get_json(f"https://api.gravatar.com/v3/profiles/{sha}")
    if not prof:
        legacy = await net.get_json(f"https://en.gravatar.com/{md5}.json")
        prof = ((legacy or {}).get("entry") or [None])[0]
    if not prof:
        return res  # no public profile: a valid "nothing found"
    name = prof.get("display_name") or prof.get("displayName") or ""
    url = prof.get("profile_url") or prof.get("profileUrl") or f"https://gravatar.com/{md5}"
    res.evidence.append(Evidence(
        source="gravatar", kind="profile", title=f"Gravatar: {name or 'public profile'}",
        url=url, snippet=prof.get("description") or prof.get("aboutMe") or "",
        entity_type="email", entity_value=email, confidence=0.85, verified=True,
        verification={"method": "first-party API (hash lookup)"},
        data={"location": prof.get("location") or prof.get("currentLocation")}))
    for acct in prof.get("verified_accounts") or prof.get("accounts") or []:
        link = acct.get("url")
        if link:
            res.evidence.append(Evidence(
                source="gravatar", kind="entity",
                title=f"Linked {acct.get('service_label') or acct.get('shortname')} account",
                url=link, snippet=link, entity_type="url", entity_value=link.lower(),
                confidence=0.8, verified=True, verification={"method": "Gravatar verified account"}))
    return res
