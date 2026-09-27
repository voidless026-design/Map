"""Work out what kind of target the user typed, and normalise it."""

from __future__ import annotations

import ipaddress
import os
import re
import urllib.parse
from typing import Optional

from openatlas.investigate.models import Target

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
_USERNAME = re.compile(r"^@?[A-Za-z0-9_.\-]{2,40}$")
_PHONE = re.compile(r"^\+?[\d\s().\-]{7,20}$")
_NAME = re.compile(r"^[^\W\d_][\w'’.\-]*(?:\s+[^\W\d_][\w'’.\-]*){1,4}$", re.UNICODE)
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".heic")


def detect(raw: str, forced: Optional[str] = None) -> Target:
    """Return a :class:`Target`. ``forced`` overrides auto-detection."""
    s = (raw or "").strip()
    kind = forced or _guess(s)
    value = _normalise(s, kind)
    return Target(raw=s, type=kind, value=value, variants=_variants(value, kind))


def _guess(s: str) -> str:
    if not s:
        return "name"
    # A path or URL ending in an image extension is an image ("photo.jpg" is not a domain).
    if s.lower().endswith(_IMAGE_EXT) and (os.path.exists(s) or "/" in s or " " not in s):
        return "image"
    if s.startswith(("http://", "https://")):
        return "url"
    if _EMAIL.match(s):
        return "email"
    try:
        ipaddress.ip_address(s)
        return "ip"
    except ValueError:
        pass
    digits = re.sub(r"\D", "", s)
    if _PHONE.match(s) and 7 <= len(digits) <= 15 and (s.startswith("+") or len(digits) >= 10):
        return "phone"
    if _DOMAIN.match(s) and " " not in s:
        return "domain"
    if " " in s and _NAME.match(s):
        return "name"
    if _USERNAME.match(s):
        return "username"
    return "name"


def _normalise(s: str, kind: str) -> str:
    if kind == "email":
        return s.lower()
    if kind == "username":
        return s.lstrip("@")
    if kind == "domain":
        return s.lower().rstrip(".")
    if kind == "url":
        return s
    if kind == "phone":
        return re.sub(r"[^\d+]", "", s)
    if kind == "name":
        return " ".join(w for w in s.split())
    return s


def _variants(value: str, kind: str) -> list:
    if kind == "name":
        parts = value.split()
        if len(parts) >= 2:
            first, last = parts[0], parts[-1]
            return [f"{first} {last}", f"{last}, {first}"] if len(parts) > 2 else [f"{last}, {first}"]
    if kind == "url":
        host = urllib.parse.urlsplit(value).hostname or ""
        return [host] if host else []
    if kind == "email":
        return [value.split("@", 1)[0]]
    return []
