"""Cross-reference findings: the same value from independent sources raises confidence."""

from __future__ import annotations

from typing import Dict, List, Tuple

from openatlas.investigate.models import Evidence


def _key(e: Evidence) -> Tuple[str, str]:
    v = (e.entity_value or "").strip().lower().rstrip("/")
    for p in ("https://", "http://", "www."):
        v = v.removeprefix(p)
    return (e.entity_type or "", v)


def correlate(evidence: List[Evidence]) -> List[Dict[str, object]]:
    """Group evidence by entity; annotate corroboration; return an entity table."""
    groups: Dict[Tuple[str, str], List[Evidence]] = {}
    for e in evidence:
        if e.entity_type and e.entity_value:
            groups.setdefault(_key(e), []).append(e)
    table = []
    for (etype, value), items in groups.items():
        sources = sorted({i.source for i in items})
        if len(sources) >= 2:
            miss = 1.0
            for i in items:
                miss *= 1 - min(i.confidence, 0.95)
            combined = min(0.97, 1 - miss)
            for i in items:
                i.corroborated_by = [s for s in sources if s != i.source]
                i.confidence = max(i.confidence, combined)
        table.append({
            "type": etype, "value": value, "sources": sources, "count": len(items),
            "confidence": round(max(i.confidence for i in items), 2),
            "confirmed": any(i.verified is True for i in items),
        })
    return sorted(table, key=lambda r: (-len(r["sources"]), -r["confidence"]))  # type: ignore[operator]
