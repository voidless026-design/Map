"""Automatic verification of findings (the osint-verify step, run on every case).

Each finding ends up Confirmed (re-checked against a live page or first-party source),
Refuted (the re-check contradicts it) or Unverified (it could not be re-checked - and the
reason is recorded). This replaces "open every link by hand to see if it's real".
"""

from __future__ import annotations

import asyncio
from typing import List

from openatlas.config import Config
from openatlas.investigate.models import Evidence, Target
from openatlas.net.client import Net

MAX_RECHECKS = 60


async def recheck_account(net: Net, t: Target, ev: Evidence) -> None:
    """Open a claimed profile page and look for the username on it."""
    r = await net.get(ev.url, page=True, max_bytes=768 * 1024)
    if r.error:
        ev.verification = {"method": "open the profile page", "result": "could not re-check",
                           "reason": r.error}
        return
    if r.status_code == 404:
        ev.verified, ev.confidence = False, 0.1
        ev.verification = {"method": "opened the profile page", "result": "page does not exist (404)"}
        return
    if r.status_code == 200 and t.value.lower() in r.text.lower():
        ev.verified, ev.confidence = True, max(ev.confidence, 0.85)
        ev.verification = {"method": "opened the profile page",
                           "result": "profile page loads and shows the username"}
        return
    ev.verification = {"method": "opened the profile page", "result": "inconclusive",
                       "reason": f"HTTP {r.status_code}; username not visible without JavaScript/login"}


async def recheck_breaches(net: Net, t: Target, items: List[Evidence]) -> None:
    """Second source for breach hits: XposedOrNot's breach-analytics endpoint."""
    data = await net.get_json(Config.services.xposedornot_analytics.format(email=t.value))
    details = ((data or {}).get("ExposedBreaches") or {}).get("breaches_details") or []
    named = {str(d.get("breach", "")).lower() for d in details}
    for ev in items:
        name = str(ev.data.get("breach", "")).lower()
        if not named:
            ev.verification = {"method": "second breach endpoint", "result": "no second source available"}
        elif name in named:
            ev.verified, ev.confidence = True, 0.9
            ev.verification = {"method": "second breach endpoint", "result": "listed in breach analytics too"}
        else:
            ev.verification = {"method": "second breach endpoint", "result": "not in breach analytics"}


async def verify_all(net: Net, t: Target, evidence: List[Evidence]) -> None:
    """Re-check every finding that is not already verified by a first-party source."""
    accounts = [e for e in evidence if e.kind == "account" and e.verified is None and e.url
                and e.source == "whatsmyname"][:MAX_RECHECKS]
    breaches = [e for e in evidence if e.kind == "breach" and e.verified is None]
    jobs = [recheck_account(net, t, e) for e in accounts]
    if breaches:
        jobs.append(recheck_breaches(net, t, breaches))
    await asyncio.gather(*jobs)
    for e in evidence:
        if e.verified is None and not e.verification:
            reason = {
                "holehe": "reported by the site's own reset/sign-up flow; can't be re-checked without logging in",
                "web-search": "search-engine snippet only; page not opened",
                "reverse-image": "a link for you to follow",
            }.get(e.source, "no independent source available")
            e.verification = {"result": "unverified", "reason": reason}
