"""Keybase user lookup: returns cryptographically proven linked accounts. Keyless."""

from __future__ import annotations

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("keybase", title="Keybase proofs", filters=("username", "people"),
        description="Keybase account and its cryptographically proven linked profiles",
        applies_to=("username",))
async def keybase(t: Target, net: Net) -> SourceResult:
    data = await net.get_json("https://keybase.io/_/api/1.0/user/lookup.json",
                              params={"usernames": t.value})
    res = SourceResult("keybase", ok=data is not None, searched=f"Keybase user '{t.value}'")
    if data is None:
        res.error = "Keybase unreachable"
        return res
    for them in data.get("them") or []:
        if not them:
            continue
        basics = them.get("basics") or {}
        uname = basics.get("username", t.value)
        res.evidence.append(Evidence(
            source="keybase", kind="account", title=f"Keybase: {uname}",
            url=f"https://keybase.io/{uname}",
            snippet=(them.get("profile") or {}).get("bio") or "",
            entity_type="username", entity_value=uname, confidence=0.85, verified=True,
            verification={"method": "first-party API"}))
        for p in (them.get("proofs_summary") or {}).get("all", []):
            res.evidence.append(Evidence(
                source="keybase", kind="entity",
                title=f"Proven {p.get('proof_type')} account: {p.get('nametag')}",
                url=p.get("service_url") or p.get("proof_url"),
                snippet=f"Keybase proof: {p.get('proof_url')}",
                entity_type="url" if p.get("proof_type") in ("dns", "generic_web_site") else "username",
                entity_value=str(p.get("nametag", "")).lower(), confidence=0.9, verified=True,
                verification={"method": "keybase cryptographic proof"}))
    return res
