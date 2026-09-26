"""robots.txt / security.txt fetching, caching and enforcement.

Every web-scraping function in OpenAtlas routes through :func:`can_fetch` before it
touches a page. This is a hard ethics gate, not a suggestion: if a site's
``robots.txt`` disallows a path for our user-agent, the fetch is refused.

The user explicitly asked to *download* ``robots.txt`` and other helpful ``.txt``
files (``security.txt``, ``humans.txt``, ``ads.txt``) - :func:`snapshot_txt_files`
does that and caches them under ``data/robots_cache/`` for the investigation record.

We only ever read public, unauthenticated resources. We never send cookies or auth
headers, never solve CAPTCHAs, and never bypass paywalls.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.robotparser
from pathlib import Path
from typing import Dict, List, Optional

import requests

from openatlas.config import Config
from openatlas.logger import get_logger

log = get_logger("openatlas.robots")

# Common informational .txt files worth snapshotting for an investigation.
KNOWN_TXT_FILES = [
    "robots.txt",
    ".well-known/security.txt",
    "security.txt",
    "humans.txt",
    "ads.txt",
    "app-ads.txt",
]

_PARSER_CACHE: Dict[str, urllib.robotparser.RobotFileParser] = {}


def _cache_dir() -> Path:
    d = Path(Config.files.robots_cache)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"Not an absolute URL: {url!r}")
    return f"{parts.scheme}://{parts.netloc}"


def _safe_name(origin: str, filename: str) -> str:
    host = urllib.parse.urlsplit(origin).netloc
    return f"{host}__{filename.replace('/', '_')}"


def _fetch_text(url: str, timeout: Optional[int] = None) -> Optional[str]:
    headers = {"User-Agent": Config.services.user_agent}
    try:
        resp = requests.get(
            url, headers=headers, timeout=timeout or Config.services.http_timeout
        )
        if resp.status_code == 200 and resp.text:
            return resp.text
        return None
    except requests.RequestException as exc:  # network hiccup - fail closed later
        log.debug("robots fetch failed for %s: %s", url, exc)
        return None


def get_parser(url: str) -> urllib.robotparser.RobotFileParser:
    """Return a cached RobotFileParser for the origin of ``url``."""
    origin = _origin(url)
    if origin in _PARSER_CACHE:
        return _PARSER_CACHE[origin]

    rp = urllib.robotparser.RobotFileParser()
    robots_url = origin + "/robots.txt"
    text = _fetch_text(robots_url)
    if text is None:
        # No robots.txt (or unreachable). Convention: absence => allow, but we
        # record that we checked.
        rp.parse([])
    else:
        rp.parse(text.splitlines())
        # Persist the snapshot the user asked for.
        try:
            (_cache_dir() / _safe_name(origin, "robots.txt")).write_text(
                text, encoding="utf-8"
            )
        except OSError:  # pragma: no cover
            pass
    _PARSER_CACHE[origin] = rp
    return rp


def can_fetch(url: str, user_agent: Optional[str] = None) -> bool:
    """Return True iff ``robots.txt`` permits fetching ``url`` for our UA."""
    ua = user_agent or Config.services.user_agent
    if not Config.ba.respect_robots:  # pragma: no cover - always True by policy
        return True
    try:
        rp = get_parser(url)
    except ValueError:
        return False
    allowed = rp.can_fetch(ua, url)
    if not allowed:
        log.warning("robots.txt DISALLOWS fetching %s - skipping (public-data-only policy).", url)
    return allowed


def guard(url: str) -> None:
    """Raise :class:`RobotsDisallowed` if ``url`` may not be fetched."""
    if not can_fetch(url):
        raise RobotsDisallowed(url)


class RobotsDisallowed(RuntimeError):
    """Raised when robots.txt forbids access to a URL."""

    def __init__(self, url: str):
        super().__init__(f"robots.txt disallows fetching: {url}")
        self.url = url


def snapshot_txt_files(domain_or_url: str) -> Dict[str, object]:
    """Download and cache robots.txt + other helpful .txt files for a site.

    Returns a manifest describing which files were found and where they were cached.
    """
    if "://" not in domain_or_url:
        domain_or_url = "https://" + domain_or_url
    origin = _origin(domain_or_url)

    manifest: Dict[str, object] = {"origin": origin, "fetched_at": int(time.time()), "files": {}}
    files_map: Dict[str, object] = manifest["files"]  # type: ignore[assignment]

    for fname in KNOWN_TXT_FILES:
        url = f"{origin}/{fname}"
        text = _fetch_text(url)
        if text is None:
            files_map[fname] = {"found": False}
            continue
        cache_path = _cache_dir() / _safe_name(origin, fname)
        try:
            cache_path.write_text(text, encoding="utf-8")
        except OSError:  # pragma: no cover
            cache_path = None  # type: ignore[assignment]
        files_map[fname] = {
            "found": True,
            "bytes": len(text),
            "cached_at": str(cache_path) if cache_path else None,
        }

    manifest_path = _cache_dir() / _safe_name(origin, "manifest.json")
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:  # pragma: no cover
        pass
    return manifest


def list_cached() -> List[str]:  # pragma: no cover - convenience
    return sorted(p.name for p in _cache_dir().glob("*"))
