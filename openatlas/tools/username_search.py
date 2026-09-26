"""UsernameCheckEngine (ucE) - username enumeration via the OSS WhatsMyName dataset.

WhatsMyName (WebBreacher/WhatsMyName, CC-BY-4.0) maps sites to a request URL and a
detection rule (expected string + HTTP code). We fetch each site's public profile URL
for the username and apply the rule. No key, public pages only.

If the dataset file is absent, the engine degrades gracefully and explains how to
fetch it (``make fetch-data``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from openatlas.config import Config
from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger
from openatlas.utils.http import api_get

log = get_logger("openatlas.tools.username")

_MAX_SITES = int(200)  # keep runs bounded/polite


def _load_sites() -> List[Dict[str, Any]]:
    path = Path(Config.files.whatsmyname)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("sites", [])
    except (ValueError, OSError) as exc:  # pragma: no cover
        log.debug("could not load WhatsMyName data: %s", exc)
        return []


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
        sites = _load_sites()
        if not sites:
            return ToolResult.unavailable(
                "check_usernames",
                "WhatsMyName dataset not found. Run `make fetch-data` to download wmn-data.json.",
                username=username,
            )
        matches: Dict[str, str] = {}
        checked = 0
        for site in sites[:_MAX_SITES]:
            try:
                uri_check = site["uri_check"].replace("{account}", username)
            except KeyError:
                continue
            checked += 1
            try:
                resp = api_get(uri_check, timeout=8)
            except Exception:
                continue
            e_code = site.get("e_code")
            e_string = site.get("e_string")
            m_code = site.get("m_code")
            m_string = site.get("m_string")
            body = resp.text or ""
            hit = resp.status_code == e_code and (e_string is None or e_string in body)
            miss = (m_code is not None and resp.status_code == m_code) or (
                m_string is not None and m_string in body
            )
            if hit and not miss:
                matches[site.get("name", uri_check)] = uri_check
        return ToolResult(
            tool_name="check_usernames",
            content={"username": username, "checked_sites": checked, "matches": matches},
            success=True,
        )
