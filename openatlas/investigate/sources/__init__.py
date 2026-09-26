"""Investigation sources: keyless public lookups that return Evidence.

Each source is an ``async def fn(target, net) -> SourceResult`` registered with
:func:`source`. The registry also drives the GUI: every source is an action button,
grouped under a filter (People, Username, Email, ...).
"""

from __future__ import annotations

import dataclasses
import importlib
import time
from typing import Awaitable, Callable, Dict, List, Tuple

from openatlas.investigate.models import SourceResult, Target
from openatlas.net.client import Net

SourceFn = Callable[[Target, Net], Awaitable[SourceResult]]

# Filter chips shown in the GUI, in order: id -> label.
FILTERS: Dict[str, str] = {
    "people": "People",
    "username": "Username",
    "email": "Email",
    "phone": "Phone",
    "web": "Domain & Web",
    "network": "IP & Network",
    "images": "Images",
    "breach": "Breach",
    "code": "Code",
}


@dataclasses.dataclass
class SourceSpec:
    id: str
    title: str
    description: str
    applies_to: Tuple[str, ...]
    filters: Tuple[str, ...]
    fn: SourceFn
    timeout: float = 40.0
    default: bool = True  # included in "Run all"

    def to_dict(self) -> Dict[str, object]:
        return {"id": self.id, "title": self.title, "description": self.description,
                "applies_to": list(self.applies_to), "filters": list(self.filters),
                "timeout": self.timeout, "default": self.default}


SOURCES: Dict[str, SourceSpec] = {}


def source(id: str, *, title: str, description: str, applies_to: Tuple[str, ...],
           filters: Tuple[str, ...], timeout: float = 40.0,
           default: bool = True) -> Callable[[SourceFn], SourceFn]:
    def deco(fn: SourceFn) -> SourceFn:
        async def timed(target: Target, net: Net) -> SourceResult:
            t0 = time.monotonic()
            res = await fn(target, net)
            res.duration_ms = int((time.monotonic() - t0) * 1000)
            return res

        SOURCES[id] = SourceSpec(id, title, description, applies_to, filters, timed,
                                 timeout, default)
        return fn

    return deco


_MODULES = ["websearch", "usernames", "github", "wiki", "reddit", "hackernews",
            "stackexchange", "keybase", "gravatar", "email", "breach", "domain", "ip",
            "phone", "image", "url"]
_loaded = False


def load() -> Dict[str, SourceSpec]:
    global _loaded
    if not _loaded:
        for m in _MODULES:
            importlib.import_module(f"openatlas.investigate.sources.{m}")
        _loaded = True
    return SOURCES


def for_target(kind: str, filter_id: str = "") -> List[SourceSpec]:
    load()
    out = [s for s in SOURCES.values() if kind in s.applies_to]
    if filter_id:
        out = [s for s in out if filter_id in s.filters]
    return out
