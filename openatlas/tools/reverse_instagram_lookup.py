"""InstagramEngine (insE) - public Instagram profile info (unauthenticated only).

Instagram heavily restricts unauthenticated access. OpenAtlas only ever reads what is
publicly visible without logging in, and always respects robots.txt. When Instagram
returns a login wall (the common case for logged-out requests), the engine reports
that honestly rather than attempting to bypass it - we do not log in, solve
challenges, or evade bot detection.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from openatlas.core.registry import BaseTool, ToolRegistry, ToolResult, ToolSpec
from openatlas.logger import get_logger
from openatlas.utils.http import scrape_get

log = get_logger("openatlas.tools.instagram")

_OG_DESC = re.compile(r'<meta property="og:description" content="([^"]+)"')
_OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"')


def _parse_public_html(html: str) -> Optional[Dict[str, Any]]:
    desc = _OG_DESC.search(html or "")
    image = _OG_IMAGE.search(html or "")
    if not desc:
        return None
    # og:description looks like: "123 Followers, 45 Following, 6 Posts - See ..."
    info: Dict[str, Any] = {"raw_description": desc.group(1)}
    m = re.search(r"([\d,\.]+)\s+Followers.*?([\d,\.]+)\s+Following.*?([\d,\.]+)\s+Posts",
                  desc.group(1))
    if m:
        info.update({
            "num_followers": m.group(1), "num_following": m.group(2), "num_posts": m.group(3),
        })
    if image:
        info["profile_picture_url"] = image.group(1)
    return info


@ToolRegistry.register("instagram-query")
class InstagramEngine(BaseTool):
    abbrev = "insE"
    description = "Public Instagram profile info via unauthenticated HTML parsing."

    specs = {
        "fetch_account_information": ToolSpec(
            name="fetch_account_information",
            description="Fetch basic public profile info for an Instagram username (no login).",
            parameters={"username": {"type": "string", "required": True, "description": "IG username"}},
            backend="public HTML", network=True, scrapes_web=True,
        ),
        "fetch_public_account_posts": ToolSpec(
            name="fetch_public_account_posts",
            description="Best-effort public post metadata via browser automation (public only).",
            parameters={"username": {"type": "string", "required": True, "description": "IG username"}},
            backend="public HTML / browser", network=True, scrapes_web=True,
        ),
    }

    @staticmethod
    def fetch_account_information(username: str) -> ToolResult:
        url = f"https://www.instagram.com/{username}/"
        resp = scrape_get(url)
        if resp is None:
            return ToolResult.failure(
                "fetch_account_information", "robots-disallowed or unreachable (public-only policy)"
            )
        if resp.status_code == 404:
            return ToolResult(tool_name="fetch_account_information",
                              content={"username": username, "exists": False}, success=True)
        info = _parse_public_html(resp.text)
        if info is None:
            return ToolResult(
                tool_name="fetch_account_information",
                content={"username": username, "exists": None,
                         "note": "Instagram returned a login wall for logged-out access; "
                                 "OpenAtlas does not log in or bypass it."},
                success=True,
            )
        info["username"] = username
        info["exists"] = True
        return ToolResult(tool_name="fetch_account_information", content=info, success=True)

    @staticmethod
    def fetch_public_account_posts(username: str) -> ToolResult:
        # Public post scraping requires JS; we delegate to the browser engine but only
        # ever on the public profile page and always robots-gated. If the browser stack
        # isn't available it degrades to a clear message.
        try:
            from openatlas.browser.engine import BrowserEngine
        except Exception as exc:
            return ToolResult.unavailable("fetch_public_account_posts",
                                          f"browser stack unavailable: {exc}")
        url = f"https://www.instagram.com/{username}/"
        eng = BrowserEngine()
        result = eng.sync_run(
            prompt=f"Open {url} and list any publicly visible post captions and image URLs. "
                   f"Do not log in. If a login wall appears, report that and stop.",
            start_url=url,
        )
        return ToolResult(tool_name="fetch_public_account_posts",
                          content={"username": username, "result": result}, success=True)
