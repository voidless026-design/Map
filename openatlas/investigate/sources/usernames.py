"""Username sweep across every site in the WhatsMyName dataset (bounded, parallel).

For each site the dataset gives a check URL (or a POST body), optional headers, and the
HTTP code + text that prove an account exists (``e_code``/``e_string``) or doesn't
(``m_code``/``m_string``). Anything else is reported as *unknown* rather than guessed.
Sites flagged ``valid: false`` are skipped; adult sites are opt-in.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from openatlas.config import Config
from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net

NSFW_CAT = "xx NSFW xx"


def load_sites() -> List[Dict[str, Any]]:
    try:
        return json.loads(open(Config.files.whatsmyname, encoding="utf-8").read()).get("sites", [])
    except (OSError, ValueError):
        return []


def _account(username: str, site: Dict[str, Any]) -> str:
    bad = site.get("strip_bad_char") or ""
    return "".join(ch for ch in username if ch not in bad)


def classify(site: Dict[str, Any], status: int, body: str) -> str:
    e_code, e_str = site.get("e_code"), site.get("e_string")
    m_code, m_str = site.get("m_code"), site.get("m_string")
    if status == e_code and (not e_str or e_str in body):
        if not (m_str and m_str in body and status == m_code):
            return "found"
    if (m_code is not None and status == m_code) and (not m_str or m_str in body):
        return "not_found"
    if m_str and m_str in body:
        return "not_found"
    return "unknown"


async def check_site(net: Net, site: Dict[str, Any], username: str) -> Dict[str, Any]:
    acct = _account(username, site)
    url = site["uri_check"].replace("{account}", acct)
    pretty = (site.get("uri_pretty") or site["uri_check"]).replace("{account}", acct)
    headers = site.get("headers") or {}
    if site.get("post_body"):
        r = await net.post(url, content=site["post_body"].replace("{account}", acct),
                           headers=headers, max_bytes=512 * 1024)
    else:
        r = await net.get(url, headers=headers, max_bytes=512 * 1024)
    status = "error" if r.error else classify(site, r.status_code, r.text)
    return {"site": site.get("name"), "category": site.get("cat"), "status": status,
            "http_status": r.status_code, "profile_url": pretty, "check_url": url,
            "protected": bool(site.get("protection")), "error": r.error}


async def sweep(username: str, net: Net, *, include_nsfw: bool = False,
                on_result: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
    import asyncio

    sites = [s for s in load_sites() if s.get("valid") is not False
             and (include_nsfw or s.get("cat") != NSFW_CAT) and "uri_check" in s]

    async def one(site: Dict[str, Any]) -> Dict[str, Any]:
        res = await check_site(net, site, username)
        if on_result:
            on_result(res)
        return res

    return list(await asyncio.gather(*(one(s) for s in sites)))


@source("whatsmyname", title="Username across 700+ sites",
        description="Checks the username on every WhatsMyName site in parallel",
        applies_to=("username",), filters=("username", "people"), timeout=120)
async def whatsmyname(t: Target, net: Net) -> SourceResult:
    sites = load_sites()
    if not sites:
        return SourceResult("whatsmyname", ok=False, searched="WhatsMyName dataset",
                            error="dataset missing - run `make fetch-data`")
    results = await sweep(t.value, net)
    found = [r for r in results if r["status"] == "found"]
    unknown = sum(1 for r in results if r["status"] in ("unknown", "error"))
    res = SourceResult(
        "whatsmyname", ok=True,
        searched=f"'{t.value}' on {len(results)} sites ({len(found)} found, {unknown} inconclusive)")
    for r in found:
        res.evidence.append(Evidence(
            source="whatsmyname", kind="account",
            title=f"{r['site']}: account '{t.value}' exists", url=r["profile_url"],
            snippet=f"HTTP {r['http_status']} with the site's 'account exists' marker",
            entity_type="username", entity_value=t.value,
            confidence=0.55 if r["protected"] else 0.7,
            data={"site": r["site"], "category": r["category"], "check_url": r["check_url"]},
        ))
    if results and not found and unknown >= 0.9 * len(results):
        res.ok, res.error = False, (f"only {len(results) - unknown} of {len(results)} sites gave a "
                                    "usable answer - check your network connection")
    return res
