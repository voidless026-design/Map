"""Breach exposure for an email via XposedOrNot (free, keyless). Defensive use only:
this reports *which* known breaches include the address - never any leaked data."""

from __future__ import annotations

from openatlas.config import Config
from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("breaches", title="Breach exposure", filters=("breach", "email"),
        description="Known public data breaches that included this email (XposedOrNot)",
        applies_to=("email",))
async def breaches(t: Target, net: Net) -> SourceResult:
    r = await net.get(Config.services.xposedornot_breaches.format(email=t.value))
    res = SourceResult("breaches", ok=not r.error, searched=f"XposedOrNot for {t.value}")
    if r.error:
        res.error = r.error
        return res
    data = r.json() or {}
    names = []
    raw = data.get("breaches")
    if isinstance(raw, list) and raw:
        names = raw[0] if isinstance(raw[0], list) else raw
    if not names:
        res.evidence.append(Evidence(
            source="breaches", kind="info", title="Not found in XposedOrNot's breach index",
            url="https://xposedornot.com/", snippet="No breach record returned for this email",
            entity_type="email", entity_value=t.value, confidence=0.6))
        return res
    for name in names:
        res.evidence.append(Evidence(
            source="breaches", kind="breach", title=f"Included in the '{name}' breach",
            url=f"https://xposedornot.com/xposed#{name}",
            snippet="Listed by XposedOrNot's public breach index",
            entity_type="email", entity_value=t.value, confidence=0.75,
            data={"breach": name}))
    return res
