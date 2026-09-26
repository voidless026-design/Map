"""OathNetEngine (OATH) - breach lookups via keyless XposedOrNot.

Policy note
-----------
Upstream OAtlas's OathNet integration retrieves both breach records *and stealer
logs*. Stealer logs are dumps of credentials exfiltrated by malware from victims'
machines. There is no legitimate, free, public source for them, and redistributing
them harms victims - so **``get_stealer_logs`` is disabled by policy** and returns an
explanatory refusal. The breach-existence lookup (does this email appear in a known
breach?) is a standard defensive check and is implemented via the keyless
XposedOrNot analytics endpoint.
"""

from __future__ import annotations

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.utils.http import api_get_json


@ToolRegistry.register("oathnet-search")
class OathNetEngine(BaseTool):
    abbrev = "OATH"
    description = "Breach lookups via keyless XposedOrNot. Stealer-log retrieval is disabled by policy."

    specs = {
        "get_breached_data": ToolSpec(
            name="get_breached_data",
            description="Query public breach datasets for an email/query via XposedOrNot (keyless).",
            parameters={"query": {"type": "string", "required": True, "description": "Email/query"}},
            backend="XposedOrNot", network=True,
        ),
        "get_stealer_logs": ToolSpec(
            name="get_stealer_logs",
            description="DISABLED by policy - returns an explanatory refusal (no legitimate free source).",
            parameters={"query": {"type": "string", "required": True, "description": "Ignored"}},
            backend="none", network=False,
            metadata={"disabled": True, "reason": "stolen-credential redistribution"},
        ),
        "combined_oathnet_search": ToolSpec(
            name="combined_oathnet_search",
            description="Run the breach lookup only (stealer-log path is disabled).",
            parameters={"query": {"type": "string", "required": True, "description": "Email/query"}},
            backend="XposedOrNot", network=True,
        ),
    }

    @staticmethod
    def get_breached_data(query: str) -> ToolResult:
        query = (query or "").strip().lower()
        data = api_get_json(Config.services.xposedornot_analytics.format(email=query))
        if data is None:
            return ToolResult.unavailable("get_breached_data", "breach API unreachable", query=query)
        return ToolResult(tool_name="get_breached_data",
                          content={"query": query, "analytics": data}, success=True,
                          metadata={"source": "xposedornot", "keyless": True})

    @staticmethod
    def get_stealer_logs(query: str) -> ToolResult:
        return ToolResult(
            tool_name="get_stealer_logs",
            content={
                "result": None,
                "reason": "Stealer-log retrieval is disabled in OpenAtlas. Stealer logs are "
                          "credentials stolen from victims by malware; there is no legitimate "
                          "free source and redistributing them harms victims. Use "
                          "get_breached_data for defensive breach-existence checks instead.",
            },
            success=False, error="disabled-by-policy",
            metadata={"disabled": True},
        )

    @staticmethod
    def combined_oathnet_search(query: str) -> ToolResult:
        breach = OathNetEngine.get_breached_data(query)
        return ToolResult(
            tool_name="combined_oathnet_search",
            content={"breach_data": breach.content,
                     "stealer_data": {"result": None, "reason": "disabled-by-policy"}},
            success=breach.success,
            error=breach.error,
        )
