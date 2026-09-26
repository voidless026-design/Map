"""Email deliverability (DNS MX) and optional Holehe account-existence checks."""

from __future__ import annotations

import asyncio

from openatlas.investigate.models import Evidence, SourceResult, Target
from openatlas.investigate.sources import source
from openatlas.net.client import Net


def _mx(domain: str) -> list:
    import dns.resolver  # type: ignore

    try:
        return sorted(str(r.exchange).rstrip(".") for r in dns.resolver.resolve(domain, "MX"))
    except Exception:
        return []


@source("email-dns", title="Email deliverability", filters=("email",),
        description="Checks the email's domain has mail servers (DNS MX records)",
        applies_to=("email",), timeout=20)
async def email_dns(t: Target, net: Net) -> SourceResult:
    domain = t.value.split("@", 1)[-1]
    mx = await asyncio.to_thread(_mx, domain)
    res = SourceResult("email-dns", ok=True, searched=f"MX records for {domain}")
    res.evidence.append(Evidence(
        source="email-dns", kind="record",
        title=f"{domain} {'accepts' if mx else 'has no'} mail servers",
        snippet=", ".join(mx) if mx else "no MX records found",
        entity_type="domain", entity_value=domain, confidence=0.9 if mx else 0.8,
        verified=True, verification={"method": "live DNS query"}, data={"mx": mx}))
    return res


@source("holehe", title="Accounts registered to email",
        description="Holehe: which sites report this email as registered (password-reset probe)",
        applies_to=("email",), filters=("email", "people"), timeout=90, default=False)
async def holehe(t: Target, net: Net) -> SourceResult:
    try:
        import httpx
        from holehe.core import get_functions, import_submodules  # type: ignore
    except Exception:
        return SourceResult("holehe", ok=False, searched="holehe",
                            error="holehe not installed (`pip install holehe`)")
    modules = import_submodules("holehe.modules")
    funcs = get_functions(modules)
    out: list = []
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(timeout=10) as client:
        async def run(fn):  # type: ignore[no-untyped-def]
            async with sem:
                try:
                    await fn(t.value, client, out)
                except Exception:
                    pass
        await asyncio.gather(*(run(f) for f in funcs))
    res = SourceResult("holehe", ok=True, searched=f"{len(funcs)} sites via holehe")
    for r in out:
        if r.get("exists"):
            res.evidence.append(Evidence(
                source="holehe", kind="account", title=f"{r.get('name')}: email is registered",
                url=f"https://{r.get('domain')}" if r.get("domain") else None,
                snippet="reported by the site's password-reset / signup check",
                entity_type="email", entity_value=t.value, confidence=0.6,
                data={"site": r.get("name"), "domain": r.get("domain")}))
    return res
