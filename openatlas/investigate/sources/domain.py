"""Domain intelligence: RDAP registration, DNS, certificate-transparency subdomains,
Wayback Machine history and published .txt files. All keyless."""

from __future__ import annotations

import asyncio
import urllib.parse
from typing import Dict, List

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net

WEB_TYPES = ("domain", "url")


def _domain(t: Target) -> str:
    if t.type == "url":
        return (urllib.parse.urlsplit(t.value).hostname or "").lower().removeprefix("www.")
    return t.value


@source("rdap", title="Domain registration (RDAP)", filters=("web",),
        description="Registrar, registration/expiry dates and nameservers via RDAP (modern WHOIS)",
        applies_to=WEB_TYPES)
async def rdap(t: Target, net: Net) -> SourceResult:
    d = _domain(t)
    data = await net.get_json(f"https://rdap.org/domain/{d}")
    res = SourceResult("rdap", ok=data is not None, searched=f"RDAP for {d}")
    if data is None:
        res.error = "no RDAP record (unsupported TLD or unreachable)"
        return res
    events = {e.get("eventAction"): e.get("eventDate") for e in data.get("events", [])}
    registrar = ""
    for ent in data.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            vcard = (ent.get("vcardArray") or [None, []])[1]
            registrar = next((v[3] for v in vcard if v and v[0] == "fn"), "") or ent.get("handle", "")
    ns = [n.get("ldhName", "").lower() for n in data.get("nameservers", [])]
    res.evidence.append(Evidence(
        source="rdap", kind="record", title=f"{d} registered via {registrar or 'unknown registrar'}",
        url=f"https://rdap.org/domain/{d}",
        snippet=f"registered {events.get('registration', '?')}, expires {events.get('expiration', '?')}; "
                f"nameservers {', '.join(ns) or '-'}",
        entity_type="domain", entity_value=d, confidence=0.9, verified=True,
        verification={"method": "authoritative RDAP"},
        data={"events": events, "nameservers": ns, "status": data.get("status")}))
    return res


def _dns(domain: str) -> Dict[str, List[str]]:
    import dns.resolver  # type: ignore

    out: Dict[str, List[str]] = {}
    for rtype in ("A", "AAAA", "MX", "NS", "TXT"):
        try:
            out[rtype] = sorted(str(r).strip('"') for r in dns.resolver.resolve(domain, rtype))
        except Exception:
            out[rtype] = []
    return out


@source("dns", title="DNS records", filters=("web", "network"),
        description="A, AAAA, MX, NS and TXT records (TXT often reveals services in use)",
        applies_to=WEB_TYPES, timeout=20)
async def dns_records(t: Target, net: Net) -> SourceResult:
    d = _domain(t)
    recs = await asyncio.to_thread(_dns, d)
    res = SourceResult("dns", ok=True, searched=f"DNS for {d}")
    for rtype, values in recs.items():
        if values:
            res.evidence.append(Evidence(
                source="dns", kind="record", title=f"{rtype} records for {d}",
                snippet="; ".join(values)[:600], entity_type="domain", entity_value=d,
                confidence=0.95, verified=True, verification={"method": "live DNS query"},
                data={"type": rtype, "values": values}))
    return res


@source("subdomains", title="Subdomains (certificates)", filters=("web",),
        description="Subdomains seen in public TLS certificate-transparency logs (crt.sh)",
        applies_to=WEB_TYPES, timeout=60)
async def subdomains(t: Target, net: Net) -> SourceResult:
    d = _domain(t)
    data = await net.get_json("https://crt.sh/", params={"q": f"%.{d}", "output": "json"},
                              max_bytes=8 * 1024 * 1024)
    res = SourceResult("subdomains", ok=data is not None, searched=f"crt.sh for *.{d}")
    if data is None:
        res.error = "crt.sh unreachable or overloaded (it often is - try again later)"
        return res
    names = sorted({n.strip().lower().lstrip("*.") for row in data
                    for n in str(row.get("name_value", "")).splitlines()
                    if n.strip().lower().endswith(d)})
    res.evidence.append(Evidence(
        source="subdomains", kind="record", title=f"{len(names)} subdomains of {d} in CT logs",
        url=f"https://crt.sh/?q=%25.{d}", snippet=", ".join(names[:40]),
        entity_type="domain", entity_value=d, confidence=0.9, verified=True,
        verification={"method": "certificate-transparency logs"}, data={"subdomains": names[:500]}))
    return res


@source("wayback", title="Website history", filters=("web",),
        description="First/last Internet Archive captures of the site (Wayback CDX API)",
        applies_to=WEB_TYPES, timeout=40)
async def wayback(t: Target, net: Net) -> SourceResult:
    d = _domain(t)
    params = {"url": d, "output": "json", "fl": "timestamp,original,statuscode",
              "collapse": "timestamp:6", "limit": "200"}
    rows = await net.get_json("https://web.archive.org/cdx/search/cdx", params=params)
    res = SourceResult("wayback", ok=rows is not None, searched=f"Wayback captures of {d}")
    if not rows or len(rows) < 2:
        if rows is None:
            res.error = "Wayback Machine unreachable"
        return res
    caps = rows[1:]
    first, last = caps[0][0], caps[-1][0]
    res.evidence.append(Evidence(
        source="wayback", kind="record",
        title=f"{d} archived since {first[:4]}-{first[4:6]} ({len(caps)} monthly captures)",
        url=f"https://web.archive.org/web/*/{d}",
        snippet=f"first capture {first}, latest in sample {last}", entity_type="domain",
        entity_value=d, confidence=0.9, verified=True,
        verification={"method": "Internet Archive CDX"}, data={"first": first, "last": last}))
    return res


@source("site-files", title="robots.txt / security.txt", filters=("web",),
        description="Downloads robots.txt, security.txt, humans.txt and ads.txt for the record",
        applies_to=WEB_TYPES, timeout=30)
async def site_files(t: Target, net: Net) -> SourceResult:
    from openatlas.utils.robots import snapshot_txt_files

    d = _domain(t)
    manifest = await asyncio.to_thread(snapshot_txt_files, d)
    found = [k for k, v in manifest.get("files", {}).items() if v.get("found")]
    res = SourceResult("site-files", ok=True, searched=f"published .txt files on {d}")
    for name in found:
        res.evidence.append(Evidence(
            source="site-files", kind="record", title=f"{d}/{name} saved",
            url=f"https://{d}/{name}", snippet=f"cached at {manifest['files'][name].get('cached_at')}",
            entity_type="domain", entity_value=d, confidence=0.9, verified=True,
            verification={"method": "downloaded"}))
    return res
