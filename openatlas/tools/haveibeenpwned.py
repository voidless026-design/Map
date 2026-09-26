"""HaveIBeenPwnedEngine (HIBP) - keyless breach checks.

Two keyless sources, no paid HIBP subscription:
* HIBP **Pwned Passwords** range API (k-anonymity: we send only a SHA-1 prefix).
* **XposedOrNot** email breach API (free, no key) for email-to-breach mapping.

We never submit a full password or a full hash - only the first 5 SHA-1 chars.
"""

from __future__ import annotations

import hashlib

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import api_get, api_get_json


@ToolRegistry.register("have-i-been-pwned")
class HaveIBeenPwnedEngine(BaseTool):
    abbrev = "HIBP"
    description = "Keyless breach checks (HIBP Pwned Passwords range API + XposedOrNot)."

    specs = {
        "check_email_against_breach_data": ToolSpec(
            name="check_email_against_breach_data",
            description="Check whether an email appears in known public breach datasets (keyless).",
            parameters={"email": {"type": "string", "required": True, "description": "Email to check"}},
            backend="XposedOrNot", network=True,
        ),
    }

    @staticmethod
    def check_email_against_breach_data(email: str) -> ToolResult:
        email = (email or "").strip().lower()
        data = api_get_json(Config.services.xposedornot_breaches.format(email=email))
        if data is None:
            return ToolResult.unavailable(
                "check_email_against_breach_data", "breach API unreachable", email=email
            )
        # XposedOrNot returns {"breaches": [[...]]} on hit, or {"Error":"Not found"} on miss.
        breaches = []
        if isinstance(data, dict):
            raw = data.get("breaches")
            if raw and isinstance(raw, list):
                breaches = raw[0] if raw and isinstance(raw[0], list) else raw
        found = bool(breaches)
        return ToolResult(
            tool_name="check_email_against_breach_data",
            content={"email": email, "found": found, "breaches": breaches},
            success=True,
            metadata={"source": "xposedornot", "keyless": True},
        )

    @staticmethod
    def check_password_exposure(password: str) -> ToolResult:
        """Bonus keyless helper: k-anonymity Pwned Passwords check (never sends the password)."""
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1[:5], sha1[5:]
        resp = None
        try:
            resp = api_get(Config.services.hibp_pwned_passwords_range.format(prefix=prefix))
        except Exception:
            resp = None
        if resp is None or resp.status_code != 200:
            return ToolResult.unavailable("check_password_exposure", "pwned-passwords API unreachable")
        count = 0
        for line in resp.text.splitlines():
            h, _, c = line.partition(":")
            if h.strip().upper() == suffix:
                count = int(c.strip() or 0)
                break
        return ToolResult(
            tool_name="check_password_exposure",
            content={"exposed": count > 0, "times_seen": count},
            success=True, metadata={"method": "k-anonymity; full hash never sent"},
        )
