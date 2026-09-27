"""Turn a fetched web page into readable text and pull out entities near the target.

Extraction is regex-based (fast, no model needed): emails, phone numbers, social profile
links and @handles. Each entity keeps the surrounding sentence as its snippet so the
user can see *why* it was attributed to the target.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Dict, List, Optional, Tuple

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<![\w/])\+?\d[\d\s().\-]{7,16}\d(?![\w/])")
HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{3,30})\b")

SOCIAL_HOSTS = {
    "github.com": "GitHub", "gitlab.com": "GitLab", "twitter.com": "X / Twitter",
    "x.com": "X / Twitter", "instagram.com": "Instagram", "facebook.com": "Facebook",
    "linkedin.com": "LinkedIn", "reddit.com": "Reddit", "youtube.com": "YouTube",
    "tiktok.com": "TikTok", "mastodon.social": "Mastodon", "bsky.app": "Bluesky",
    "medium.com": "Medium", "stackoverflow.com": "Stack Overflow", "keybase.io": "Keybase",
    "t.me": "Telegram", "twitch.tv": "Twitch", "pinterest.com": "Pinterest",
    "soundcloud.com": "SoundCloud", "behance.net": "Behance", "dribbble.com": "Dribbble",
}
_SKIP_EMAIL_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "domain.com")


def page_text(html: str, *, max_chars: int = 200_000) -> Tuple[str, str, List[str]]:
    """Return (title, main_text, links) from raw HTML, dropping scripts/nav/boilerplate."""
    try:
        from bs4 import BeautifulSoup
    except Exception:  # pragma: no cover - bs4 is a core dependency
        return "", re.sub(r"<[^>]+>", " ", html)[:max_chars], []
    soup = BeautifulSoup(html[: max_chars * 3], "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    links = [a.get("href") for a in soup.find_all("a", href=True)][:500]
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header",
                     "aside", "form", "iframe"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return title[:300], text[:max_chars], [x for x in links if isinstance(x, str)]


def context(text: str, start: int, end: int, width: int = 120) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def find_mentions(text: str, needles: List[str]) -> List[Tuple[int, int]]:
    """Case-insensitive positions of any needle in text."""
    spans: List[Tuple[int, int]] = []
    low = text.lower()
    for n in needles:
        n = n.lower().strip()
        if len(n) < 3:
            continue
        i = low.find(n)
        while i != -1 and len(spans) < 50:
            spans.append((i, i + len(n)))
            i = low.find(n, i + len(n))
    return sorted(spans)


def social_profile(url: str) -> Optional[Dict[str, str]]:
    """If ``url`` is a profile on a known social site, return {site, handle, url}."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    site = SOCIAL_HOSTS.get(host)
    if not site:
        return None
    path = [p for p in parts.path.split("/") if p]
    if not path:
        return None
    skip = {"search", "share", "sharer", "intent", "hashtag", "explore", "login", "signup",
            "watch", "p", "status", "about", "help", "privacy", "terms", "home", "settings"}
    handle = path[1] if host.startswith("linkedin.com") and len(path) > 1 and path[0] in {"in", "company"} \
        else (path[1] if path[0] in {"user", "u", "c"} and len(path) > 1 else path[0])
    handle = handle.lstrip("@")
    if not handle or handle.lower() in skip or len(handle) > 60:
        return None
    return {"site": site, "handle": handle, "url": url}


def entities_near(text: str, needles: List[str], *, window: int = 600) -> List[Dict[str, str]]:
    """Entities found within ``window`` characters of a mention of the target."""
    found: Dict[Tuple[str, str], Dict[str, str]] = {}
    for start, end in find_mentions(text, needles)[:20]:
        a, b = max(0, start - window), min(len(text), end + window)
        chunk = text[a:b]
        for m in EMAIL_RE.finditer(chunk):
            v = m.group(0).lower()
            if not v.endswith(_SKIP_EMAIL_DOMAINS):
                found.setdefault(("email", v), {"type": "email", "value": v,
                                                "snippet": context(chunk, m.start(), m.end())})
        for m in PHONE_RE.finditer(chunk):
            digits = re.sub(r"\D", "", m.group(0))
            if 8 <= len(digits) <= 15 and not re.fullmatch(r"(19|20)\d{6}", digits):
                found.setdefault(("phone", digits), {"type": "phone", "value": m.group(0).strip(),
                                                     "snippet": context(chunk, m.start(), m.end())})
        for m in HANDLE_RE.finditer(chunk):
            v = m.group(1)
            found.setdefault(("handle", v.lower()), {"type": "username", "value": v,
                                                     "snippet": context(chunk, m.start(), m.end())})
    return list(found.values())
