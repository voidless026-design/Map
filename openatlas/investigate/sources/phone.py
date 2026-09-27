"""Phone number facts from Google's open-source ``phonenumbers`` library (fully offline)."""

from __future__ import annotations

import os

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


@source("phone-info", title="Phone number facts", filters=("phone",),
        description="Validity, country/region, line type, original carrier and time zone (offline)",
        applies_to=("phone",), timeout=10)
async def phone_info(t: Target, net: Net) -> SourceResult:
    try:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone
    except Exception:
        return SourceResult("phone-info", ok=False, searched="phonenumbers",
                            error="phonenumbers not installed")
    region = os.getenv("OPENATLAS_DEFAULT_REGION", "US")
    res = SourceResult("phone-info", ok=True, searched=f"offline number analysis ({region} default)")
    try:
        n = phonenumbers.parse(t.value, region)
    except phonenumbers.NumberParseException as exc:
        res.ok, res.error = False, f"not a parseable phone number: {exc}"
        return res
    types = {v: k for k, v in vars(phonenumbers.PhoneNumberType).items() if not k.startswith("_")}
    valid = phonenumbers.is_valid_number(n)
    e164 = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    where = geocoder.description_for_number(n, "en") or phonenumbers.region_code_for_number(n)
    line = types.get(phonenumbers.number_type(n), "UNKNOWN").replace("_", " ").lower()
    orig_carrier = carrier.name_for_number(n, "en")
    res.evidence.append(Evidence(
        source="phone-info", kind="info",
        title=f"{e164}: {'valid' if valid else 'NOT a valid'} {line} number, {where or 'unknown region'}",
        snippet=f"original carrier {orig_carrier or 'unknown'}; time zones "
                f"{', '.join(timezone.time_zones_for_number(n)) or '-'}",
        entity_type="phone", entity_value=e164, confidence=0.9 if valid else 0.5, verified=valid,
        verification={"method": "libphonenumber numbering plan (offline)"},
        data={"valid": valid, "region": where, "line_type": line, "carrier": orig_carrier}))
    return res
