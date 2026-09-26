"""EmailCheckEngine (ecE) - keyless email validation via syntax + DNS/MX.

Replaces nothing paid; upstream OAtlas already did this locally. We add MX lookup
without ever connecting to send mail (no SMTP callback that could be abusive).
"""

from __future__ import annotations

import re

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.email")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$")


@ToolRegistry.register("email-verification")
class EmailCheckEngine(BaseTool):
    abbrev = "ecE"
    description = "Validate email addresses using syntax + DNS/MX checks (keyless)."

    specs = {
        "verify_email_address": ToolSpec(
            name="verify_email_address",
            description="Verify if an email address is syntactically valid and its domain accepts mail.",
            parameters={"email": {"type": "string", "required": True, "description": "Email to verify"}},
            backend="dns (local resolver)",
            network=True,
        )
    }

    @staticmethod
    def verify_email_address(email: str) -> ToolResult:
        email = (email or "").strip()
        m = _EMAIL_RE.match(email)
        if not m:
            return ToolResult(
                tool_name="verify_email_address",
                content={"email": email, "valid_syntax": False, "has_mx": False, "deliverable": False},
                success=True,
            )
        domain = m.group(1)
        has_mx = False
        mx_hosts = []
        try:
            import dns.resolver  # type: ignore

            answers = dns.resolver.resolve(domain, "MX")
            mx_hosts = sorted(str(r.exchange).rstrip(".") for r in answers)
            has_mx = bool(mx_hosts)
        except Exception as exc:  # missing dnspython or no MX record
            log.debug("MX lookup failed for %s: %s", domain, exc)
            # Fall back to an A record check as a weaker signal.
            try:
                import dns.resolver  # type: ignore

                dns.resolver.resolve(domain, "A")
                has_mx = True  # domain resolves; may accept mail
            except Exception:
                has_mx = False

        return ToolResult(
            tool_name="verify_email_address",
            content={
                "email": email,
                "domain": domain,
                "valid_syntax": True,
                "has_mx": has_mx,
                "mx_hosts": mx_hosts,
                "deliverable": has_mx,  # best-effort; we never do an SMTP RCPT probe
            },
            success=True,
            metadata={"note": "deliverability is inferred from MX/A only; no SMTP probe performed"},
        )
