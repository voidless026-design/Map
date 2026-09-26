"""ProfessionalEmailFinderEngine (PEF) - keyless email discovery (replaces Hunter.io).

Strategy without any paid API:
* Generate common email permutations for a person at a domain.
* Verify the domain has MX (via EmailCheckEngine).
* Optionally corroborate account existence with Holehe (if installed) - Holehe probes
  public "forgot password" flows and needs no key.
"""

from __future__ import annotations

from typing import List

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger
from openatlas.tools.email_checker import EmailCheckEngine

log = get_logger("openatlas.tools.pef")


def _permutations(first: str, last: str, domain: str) -> List[str]:
    f, l = first.lower(), last.lower()
    fi, li = f[:1], l[:1]
    patterns = [f"{f}.{l}", f"{f}{l}", f"{fi}{l}", f"{f}{li}", f"{f}", f"{f}_{l}",
                f"{l}.{f}", f"{l}{f}", f"{fi}.{l}"]
    return [f"{p}@{domain}" for p in dict.fromkeys(patterns)]


@ToolRegistry.register("professional-email-finder")
class ProfessionalEmailFinderEngine(BaseTool):
    abbrev = "PEF"
    description = "Discover likely emails via permutations + MX + Holehe (no Hunter.io key)."

    specs = {
        "find_emails_for_domain": ToolSpec(
            name="find_emails_for_domain",
            description="Enumerate likely professional email patterns for a domain (heuristic + MX).",
            parameters={"domain_name": {"type": "string", "required": True, "description": "Domain"}},
            backend="dns MX", network=True,
        ),
        "find_emails_for_person": ToolSpec(
            name="find_emails_for_person",
            description="Derive and verify the most likely email for a person at a domain.",
            parameters={
                "domain_name": {"type": "string", "required": True, "description": "Domain"},
                "first_name": {"type": "string", "required": True, "description": "First name"},
                "last_name": {"type": "string", "required": True, "description": "Last name"},
            },
            backend="dns MX + holehe", network=True,
        ),
    }

    @staticmethod
    def find_emails_for_domain(domain_name: str) -> ToolResult:
        domain_name = (domain_name or "").strip().lower()
        # Verify domain accepts mail using a probe address.
        mx = EmailCheckEngine.verify_email_address(f"info@{domain_name}")
        has_mx = mx.content.get("has_mx", False)
        common = ["info", "contact", "hello", "support", "sales", "admin", "careers", "press"]
        candidates = [f"{p}@{domain_name}" for p in common]
        return ToolResult(
            tool_name="find_emails_for_domain",
            content={"domain": domain_name, "accepts_mail": has_mx,
                     "mx_hosts": mx.content.get("mx_hosts", []), "common_addresses": candidates},
            success=True,
            metadata={"note": "heuristic patterns; no paid enrichment"},
        )

    @staticmethod
    def find_emails_for_person(domain_name: str, first_name: str, last_name: str) -> ToolResult:
        domain_name = (domain_name or "").strip().lower()
        cands = _permutations(first_name, last_name, domain_name)
        mx = EmailCheckEngine.verify_email_address(cands[0])
        has_mx = mx.content.get("has_mx", False)

        holehe_result = None
        try:  # optional corroboration; never required
            import asyncio

            import httpx  # noqa: F401  (holehe dependency)
            from holehe.core import import_submodules  # type: ignore

            best = cands[0]

            async def _run():
                modules = import_submodules("holehe.modules")
                out = []
                async with httpx.AsyncClient() as client:
                    for _, mod in list(modules.items())[:15]:  # cap for speed
                        fn = [v for k, v in vars(mod).items() if k == mod.__name__.split(".")[-1]]
                        if not fn:
                            continue
                        res: list = []
                        try:
                            await fn[0](best, client, res)
                            out.extend([r for r in res if r.get("exists")])
                        except Exception:
                            continue
                return out

            holehe_result = asyncio.run(_run())
        except Exception as exc:
            log.debug("holehe corroboration unavailable: %s", exc)

        return ToolResult(
            tool_name="find_emails_for_person",
            content={
                "domain": domain_name, "candidates": cands,
                "most_likely": cands[0], "accepts_mail": has_mx,
                "holehe_accounts": holehe_result,
            },
            success=True,
            metadata={"note": "ranked heuristically; holehe corroboration optional/keyless"},
        )
