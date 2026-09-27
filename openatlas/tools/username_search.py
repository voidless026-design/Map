"""UsernameCheckEngine (ucE) - username enumeration via the OSS WhatsMyName dataset.

Delegates to the bounded, parallel sweep in ``openatlas.investigate.sources.usernames``
(all 717 sites, each site's own headers/POST body/character rules). It used to check the
first 200 sites one at a time with an 8 s timeout each, which could hang for many minutes.
No key, public pages only. If the dataset is missing it explains how to fetch it.
"""

from __future__ import annotations

from typing import Any, Dict, List

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger

log = get_logger("openatlas.tools.username")


async def _sweep(username: str) -> List[Dict[str, Any]]:
    from openatlas.investigate.sources.usernames import sweep
    from openatlas.net.client import Net

    async with Net() as net:
        return await sweep(username, net)


@ToolRegistry.register("username-enumeration")
class UsernameCheckEngine(BaseTool):
    abbrev = "ucE"
    description = "Check a username across many sites using the OSS WhatsMyName dataset."

    specs = {
        "check_usernames": ToolSpec(
            name="check_usernames",
            description="Test a username across public sites and return the matches.",
            parameters={"username": {"type": "string", "required": True, "description": "Username"}},
            backend="WhatsMyName dataset", network=True,
        ),
    }

    @staticmethod
    def check_usernames(username: str) -> ToolResult:
        from openatlas.investigate.sources.usernames import load_sites
        from openatlas.net.aio import run_sync

        if not load_sites():
            return ToolResult.unavailable(
                "check_usernames",
                "WhatsMyName dataset not found. Run `make fetch-data` to download wmn-data.json.",
                username=username,
            )
        results = run_sync(_sweep(username))
        matches = {r["site"]: r["profile_url"] for r in results if r["status"] == "found"}
        return ToolResult(
            tool_name="check_usernames",
            content={
                "username": username,
                "checked_sites": len(results),
                "matches": matches,
                "inconclusive": sum(1 for r in results if r["status"] in ("unknown", "error")),
            },
            success=True,
        )
