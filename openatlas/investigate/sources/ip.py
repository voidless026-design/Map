"""IP intelligence: RDAP network owner, geolocation (ip-api) and reverse DNS. Keyless."""

from __future__ import annotations

import asyncio
import socket

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("ip-owner", title="IP owner (RDAP)", filters=("network",),
        description="Network name, owning organisation, country and range via RDAP",
        applies_to=("ip",))
async def ip_owner(t: Target, net: Net) -> SourceResult:
    data = await net.get_json(f"https://rdap.org/ip/{t.value}")
    res = SourceResult("ip-owner", ok=data is not None, searched=f"RDAP for {t.value}")
    if data is None:
        res.error = "RDAP unreachable"
        return res
    rng = f"{data.get('startAddress')} - {data.get('endAddress')}"
    res.evidence.append(Evidence(
        source="ip-owner", kind="record", title=f"{t.value} belongs to {data.get('name', '?')}",
        url=f"https://rdap.org/ip/{t.value}", snippet=f"range {rng}, country {data.get('country', '?')}",
        entity_type="ip", entity_value=t.value, confidence=0.9, verified=True,
        verification={"method": "authoritative RDAP"},
        data={"name": data.get("name"), "country": data.get("country"), "range": rng}))
    return res


@source("ip-geo", title="IP geolocation", filters=("network",),
        description="Approximate location, ISP and ASN (ip-api.com, keyless)",
        applies_to=("ip",))
async def ip_geo(t: Target, net: Net) -> SourceResult:
    data = await net.get_json(f"http://ip-api.com/json/{t.value}",
                              params={"fields": "status,country,regionName,city,isp,org,as,query"})
    res = SourceResult("ip-geo", ok=bool(data) and data.get("status") == "success",
                       searched=f"ip-api for {t.value}")
    if not res.ok:
        res.error = "lookup failed"
        return res
    res.evidence.append(Evidence(
        source="ip-geo", kind="info",
        title=f"{t.value} ~ {data.get('city')}, {data.get('regionName')}, {data.get('country')}",
        snippet=f"ISP {data.get('isp')}; {data.get('as')}", entity_type="ip", entity_value=t.value,
        confidence=0.6, data=data))
    return res


@source("reverse-dns", title="Reverse DNS", filters=("network",),
        description="Hostname the IP points back to (PTR record)", applies_to=("ip",), timeout=15)
async def reverse_dns(t: Target, net: Net) -> SourceResult:
    res = SourceResult("reverse-dns", ok=True, searched=f"PTR for {t.value}")
    try:
        host = (await asyncio.to_thread(socket.gethostbyaddr, t.value))[0]
    except (OSError, socket.herror):
        return res
    res.evidence.append(Evidence(
        source="reverse-dns", kind="record", title=f"{t.value} -> {host}", snippet=host,
        entity_type="domain", entity_value=host.lower(), confidence=0.9, verified=True,
        verification={"method": "live DNS query"}))
    return res
