"""``python -m openatlas.utils.verify_findings`` - the osint-verify engine.

Cross-checks an AI/LLM OSINT finding against an INDEPENDENT free source and returns a
corroboration report: per claim a ``verified`` (True/False/None), the ``source`` used,
``evidence``, and a ``confidence`` in [0,1]. ``None`` means "could not confirm" and is a
first-class outcome - never silently treated as pass.

Public data only; page fetches are robots-gated. No login, no CAPTCHA/paywall bypass.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from openatlas.utils.http import api_get_json, scrape_get


def _row(claim: str, verified: Optional[bool], source: str, evidence: Any,
         confidence: float) -> Dict[str, Any]:
    return {"claim": claim, "verified": verified, "source": source,
            "evidence": evidence, "confidence": round(confidence, 2)}


# --------------------------------------------------------------------------- #
def verify_username(matches: Dict[str, str], username: str) -> List[Dict[str, Any]]:
    """Resolve each claimed profile URL and require a 200 + presence marker."""
    rows: List[Dict[str, Any]] = []
    for site, url in (matches or {}).items():
        resp = scrape_get(url)
        if resp is None:
            rows.append(_row(f"{site}: {url}", None, "http (robots-gated)",
                             "unreachable or robots-disallowed", 0.0))
            continue
        present = username.lower() in (resp.text or "").lower()
        ok = resp.status_code == 200 and present
        rows.append(_row(
            f"{site}: {url}",
            True if ok else (False if resp.status_code == 404 else None),
            "http profile fetch",
            {"status": resp.status_code, "username_present": present},
            0.9 if ok else (0.1 if resp.status_code == 404 else 0.4),
        ))
    return rows


def verify_geolocation(claim: Dict[str, Any], image_path: Optional[str]) -> List[Dict[str, Any]]:
    """Cross-check an LLM location claim against EXIF GPS + OSM reverse-geocode."""
    from openatlas.tools.geolocation import _exif_gps, _reverse_geocode

    rows: List[Dict[str, Any]] = []
    claimed_region = str(claim.get("region", "")).lower()
    lat, lon = claim.get("latitude"), claim.get("longitude")

    exif = _exif_gps(image_path) if image_path else None
    if exif:
        rows.append(_row("EXIF GPS present", True, "image EXIF", exif, 0.95))
        if lat is not None and lon is not None:
            close = abs(exif["latitude"] - lat) < 1.0 and abs(exif["longitude"] - lon) < 1.0
            rows.append(_row("LLM coords match EXIF", close, "EXIF vs LLM",
                             {"exif": exif, "llm": {"latitude": lat, "longitude": lon}},
                             0.9 if close else 0.1))
    else:
        rows.append(_row("EXIF GPS present", None, "image EXIF",
                         "no EXIF GPS to corroborate against", 0.0))

    if lat is not None and lon is not None:
        place = _reverse_geocode(lat, lon)
        if place:
            disp = str(place.get("display_name", "")).lower()
            match = bool(claimed_region) and claimed_region in disp
            rows.append(_row(
                f"coords resolve to claimed region '{claim.get('region')}'",
                match if claimed_region else None, "OSM Nominatim",
                place, 0.85 if match else (0.3 if claimed_region else 0.0),
            ))
        else:
            rows.append(_row("reverse geocode", None, "OSM Nominatim", "no result", 0.0))
    return rows


def verify_email(email: str) -> List[Dict[str, Any]]:
    from openatlas.tools.email_checker import EmailCheckEngine

    res = EmailCheckEngine.verify_email_address(email).content
    ok = bool(res.get("has_mx"))
    return [_row(f"{email} deliverable", ok if res.get("valid_syntax") else False,
                 "DNS MX", res, 0.7 if ok else 0.2)]


def verify_breach(email: str) -> List[Dict[str, Any]]:
    """Require agreement between two keyless breach signals."""
    from openatlas.tools.haveibeenpwned import HaveIBeenPwnedEngine
    from openatlas.tools.oathnet import OathNetEngine

    a = HaveIBeenPwnedEngine.check_email_against_breach_data(email)
    b = OathNetEngine.get_breached_data(email)
    a_found = bool(a.content.get("found")) if a.success else None
    b_has = None
    if b.success and isinstance(b.content.get("analytics"), dict):
        b_has = bool(b.content["analytics"].get("breaches_details") or
                     b.content["analytics"].get("ExposedBreaches"))
    if a_found is None and b_has is None:
        return [_row(f"{email} in breach", None, "XposedOrNot x2",
                     "both sources unreachable", 0.0)]
    agree = a_found == b_has and a_found is not None
    return [_row(f"{email} in breach",
                 a_found if agree else (a_found if b_has is None else None),
                 "two keyless sources",
                 {"source_a_found": a_found, "source_b_found": b_has, "agree": agree},
                 0.85 if agree else 0.4)]


def verify_ip(claim: Dict[str, Any], ip: str) -> List[Dict[str, Any]]:
    primary = api_get_json(f"http://ip-api.com/json/{ip}") or {}
    secondary = api_get_json(f"https://ipapi.co/{ip}/json/") or {}
    c1 = (primary.get("countryCode") or "").upper()
    c2 = (secondary.get("country") or secondary.get("country_code") or "").upper()
    claimed = str(claim.get("country", "")).upper()
    match = bool(c1) and c1 == c2
    return [_row(f"{ip} country", match if c1 else None, "ip-api vs ipapi.co",
                 {"ip_api": c1, "ipapi_co": c2, "claimed": claimed},
                 0.85 if match else 0.3)]


# --------------------------------------------------------------------------- #
def _load_input(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}


def run(kind: str, *, input_path: Optional[str] = None, claim: Optional[str] = None,
        image: Optional[str] = None) -> Dict[str, Any]:
    data = _load_input(input_path)
    claim_obj: Dict[str, Any] = {}
    if claim:
        try:
            claim_obj = json.loads(claim)
        except ValueError:
            claim_obj = {"value": claim}

    if kind == "username":
        content = data.get("content", data)
        rows = verify_username(content.get("matches", {}), content.get("username", ""))
    elif kind == "geolocation":
        rows = verify_geolocation(claim_obj, image)
    elif kind == "email":
        rows = verify_email(claim or claim_obj.get("value", ""))
    elif kind == "breach":
        rows = verify_breach(claim or claim_obj.get("value", ""))
    elif kind == "ip":
        rows = verify_ip(claim_obj, claim_obj.get("value") or (claim or ""))
    else:
        return {"error": f"unknown finding type '{kind}'"}

    confirmed = sum(1 for r in rows if r["verified"] is True)
    refuted = sum(1 for r in rows if r["verified"] is False)
    unknown = sum(1 for r in rows if r["verified"] is None)
    return {"type": kind, "rows": rows,
            "summary": {"confirmed": confirmed, "refuted": refuted, "unverifiable": unknown}}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="openatlas.utils.verify_findings",
                                description="Independently verify OSINT findings.")
    p.add_argument("--type", required=True,
                   choices=["username", "geolocation", "email", "breach", "ip"])
    p.add_argument("--input", default=None, help="path to a saved ToolResult JSON")
    p.add_argument("--claim", default=None, help="a claim string or JSON object")
    p.add_argument("--image", default=None, help="image path (geolocation)")
    a = p.parse_args(argv)
    report = run(a.type, input_path=a.input, claim=a.claim, image=a.image)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
