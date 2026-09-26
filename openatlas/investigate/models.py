"""Data model for investigations: targets, evidence and per-source results."""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
from typing import Any, Dict, List, Optional

TARGET_TYPES = ("email", "username", "name", "phone", "domain", "url", "ip", "image")

# Evidence kinds shown in the UI.
KINDS = ("account", "profile", "mention", "entity", "breach", "record", "info", "link")


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


@dataclasses.dataclass
class Target:
    raw: str
    type: str
    value: str  # normalised form used for queries
    variants: List[str] = dataclasses.field(default_factory=list)  # alternate spellings

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Evidence:
    """One finding, always traceable to where it came from."""

    source: str  # source id, e.g. "web-search", "whatsmyname", "github"
    kind: str  # one of KINDS
    title: str  # human-readable one-liner
    url: Optional[str] = None  # where to see it yourself
    snippet: str = ""  # the text that supports it
    entity_type: Optional[str] = None  # email / username / phone / url / domain / name ...
    entity_value: Optional[str] = None
    confidence: float = 0.5  # 0..1
    verified: Optional[bool] = None  # True confirmed / False refuted / None not re-checked
    verification: Dict[str, Any] = dataclasses.field(default_factory=dict)
    data: Dict[str, Any] = dataclasses.field(default_factory=dict)
    retrieved_at: str = dataclasses.field(default_factory=now_iso)
    corroborated_by: List[str] = dataclasses.field(default_factory=list)

    @property
    def id(self) -> str:
        key = f"{self.source}|{self.kind}|{self.url}|{self.entity_type}|{self.entity_value}|{self.title}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    @property
    def status(self) -> str:
        return {True: "confirmed", False: "refuted", None: "unverified"}[self.verified]

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["id"] = self.id
        d["status"] = self.status
        return d


@dataclasses.dataclass
class SourceResult:
    source: str
    ok: bool
    searched: str  # plain-English description of what was looked up
    evidence: List[Evidence] = dataclasses.field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source, "ok": self.ok, "searched": self.searched,
            "error": self.error, "duration_ms": self.duration_ms,
            "found": len(self.evidence),
        }
