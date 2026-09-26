"""Shared HTTP helpers: truthful UA, timeouts, and optional robots enforcement.

* :func:`api_get` / :func:`api_get_json` are for hitting *public APIs* (Reddit
  JSON, GitHub REST, ip-api, XposedOrNot, ...). These are documented, keyless
  endpoints, so they are not gated by robots.txt (robots governs crawling of a
  site's pages, not its published APIs) - but they always send our honest UA.
* :func:`scrape_get` is for fetching arbitrary *web pages* and IS robots-gated.

Nothing here ever sends cookies, auth headers, or credentials.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from openatlas.config import Config
from openatlas.logger import get_logger
from openatlas.utils.robots import guard

log = get_logger("openatlas.http")


def _headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    h = {"User-Agent": Config.services.user_agent, "Accept": "*/*"}
    if extra:
        h.update(extra)
    return h


def api_get(
    url: str, *, params: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> requests.Response:
    """GET a public API endpoint (not robots-gated). Raises on transport errors."""
    return requests.get(
        url,
        params=params,
        headers=_headers(headers),
        timeout=timeout or Config.services.http_timeout,
    )


def api_get_json(
    url: str, *, params: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    """GET a public API endpoint and parse JSON. Returns None on non-200/parse error."""
    try:
        resp = api_get(url, params=params, timeout=timeout, headers=headers)
    except requests.RequestException as exc:
        log.debug("api_get failed for %s: %s", url, exc)
        return None
    if resp.status_code != 200:
        log.debug("api_get non-200 (%s) for %s", resp.status_code, url)
        return None
    try:
        return resp.json()
    except ValueError:
        log.debug("api_get non-JSON body for %s", url)
        return None


def scrape_get(
    url: str, *, timeout: Optional[int] = None, headers: Optional[Dict[str, str]] = None
) -> Optional[requests.Response]:
    """Fetch a web page, enforcing robots.txt first. Returns None if disallowed/failed."""
    from openatlas.utils.robots import RobotsDisallowed

    try:
        guard(url)
    except RobotsDisallowed:
        return None
    try:
        return requests.get(
            url, headers=_headers(headers), timeout=timeout or Config.services.http_timeout
        )
    except requests.RequestException as exc:
        log.debug("scrape_get failed for %s: %s", url, exc)
        return None
