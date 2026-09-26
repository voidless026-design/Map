"""IPinfoEngine (ipE) - IP & ASN lookups via keyless public APIs.

Replaces IPinfo's paid tiers with ip-api.com (free), ipapi.co (free), and RIPEstat
(free) for ASN. No token required.
"""

from __future__ import annotations

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import api_get_json


@ToolRegistry.register("ip-lookups")
class IPinfoEngine(BaseTool):
    abbrev = "ipE"
    description = "IP and ASN lookups via keyless public APIs."

    specs = {
        "basic_ip_lookup": ToolSpec(
            name="basic_ip_lookup",
            description="Free-tier geolocation/ownership lookup for an IP (ip-api.com).",
            parameters={"ipaddress": {"type": "string", "required": True, "description": "IP address"}},
            backend="ip-api.com", network=True,
        ),
        "core_api_lookups": ToolSpec(
            name="core_api_lookups",
            description="Enriched IP lookup aggregating multiple keyless sources.",
            parameters={"ipaddress": {"type": "string", "required": True, "description": "IP address"}},
            backend="ip-api.com + ipapi.co", network=True,
        ),
        "core_api_lookups_asn": ToolSpec(
            name="core_api_lookups_asn",
            description="Look up an Autonomous System (ASN) via RIPEstat (keyless).",
            parameters={"asn_number": {"type": "string", "required": True, "description": "ASN digits"}},
            backend="RIPEstat", network=True,
        ),
    }

    @staticmethod
    def basic_ip_lookup(ipaddress: str) -> ToolResult:
        data = api_get_json(Config.services.ip_api.format(ip=ipaddress))
        if not data or data.get("status") == "fail":
            return ToolResult.failure("basic_ip_lookup", f"lookup failed for {ipaddress}")
        return ToolResult(tool_name="basic_ip_lookup", content=data, success=True)

    @staticmethod
    def core_api_lookups(ipaddress: str) -> ToolResult:
        primary = api_get_json(Config.services.ip_api.format(ip=ipaddress)) or {}
        secondary = api_get_json(Config.services.ipapi_co.format(ip=ipaddress)) or {}
        if not primary and not secondary:
            return ToolResult.failure("core_api_lookups", f"no data for {ipaddress}")
        return ToolResult(
            tool_name="core_api_lookups",
            content={"ip_api": primary, "ipapi_co": secondary}, success=True,
        )

    @staticmethod
    def core_api_lookups_asn(asn_number: str) -> ToolResult:
        asn = str(asn_number).lstrip("AS").strip()
        data = api_get_json(Config.services.ripestat_asn.format(asn=asn))
        if not data or "data" not in data:
            return ToolResult.failure("core_api_lookups_asn", f"no data for AS{asn}")
        return ToolResult(tool_name="core_api_lookups_asn", content=data["data"], success=True)
