"""Stack Exchange users by display name (public API, keyless, 300 requests/day/IP)."""

from __future__ import annotations

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("stackexchange", title="Stack Overflow users", filters=("people", "username", "code"),
        description="Stack Overflow accounts whose display name matches the target",
        applies_to=("name", "username"))
async def stackexchange(t: Target, net: Net) -> SourceResult:
    data = await net.get_json("https://api.stackexchange.com/2.3/users",
                              params={"inname": t.value, "site": "stackoverflow",
                                      "pagesize": 5, "order": "desc", "sort": "reputation"})
    res = SourceResult("stackexchange", ok=data is not None,
                       searched=f"Stack Overflow users named '{t.value}'")
    if data is None:
        res.error = "Stack Exchange API unreachable or daily quota used"
        return res
    for u in data.get("items", []):
        name = u.get("display_name", "")
        exact = name.lower() == t.value.lower()
        res.evidence.append(Evidence(
            source="stackexchange", kind="account", title=f"Stack Overflow: {name}",
            url=u.get("link"), snippet=f"reputation {u.get('reputation')}, location "
            f"{u.get('location') or '-'}", entity_type="username", entity_value=name,
            confidence=0.6 if exact else 0.3, verified=True,
            verification={"method": "first-party API"},
            data={"location": u.get("location"), "website": u.get("website_url")}))
    return res
