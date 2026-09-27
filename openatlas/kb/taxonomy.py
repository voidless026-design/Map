"""Parse the fields-of-study manifest into ingestion seeds.

Format: ``## N. Division`` headings, optional ``### Area`` headings, and lines of subjects
separated by ``·`` (or commas). Subjects directly under a division (no ``###``) take the
division as their area. Parsing stops at the "Using this as an ingestion manifest" section.
Qualifiers such as "Endocrinology (clinical)" keep their label but look up the base title.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from openatlas.config import Config

_STOP = re.compile(r"^##\s+(using this|machine-readable)", re.I)
_QUALIFIER = re.compile(r"\s*\(([^)]*)\)\s*$")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def lookup_title(label: str) -> str:
    """Wikipedia title to try for a label: drop a trailing '(qualifier)'."""
    return _QUALIFIER.sub("", label).strip()


def parse(path: Optional[str] = None) -> List[Dict[str, object]]:
    """Return unique seeds: {title, label, divisions, areas, namespaces}."""
    text = Path(path or Config.files.taxonomy).read_text(encoding="utf-8")
    division = area = ""
    seeds: Dict[str, Dict[str, object]] = {}
    in_code = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line == "---" or line.startswith(("#", ">", "(", "-", "*")) \
                and not line.startswith("##"):
            if not line.startswith("#"):
                continue
        if _STOP.match(line):
            break
        if line.startswith("### "):
            area = line[4:].strip()
            continue
        if line.startswith("## "):
            division = re.sub(r"^\d+\.\s*", "", line[3:].strip())
            area = division
            continue
        if line.startswith("#") or not division:
            continue
        parts = [p.strip() for p in (line.split("·") if "·" in line else line.split(","))]
        for label in parts:
            if not label or len(label) > 80:
                continue
            title = lookup_title(label)
            key = title.lower()
            seed = seeds.setdefault(key, {"title": title, "label": label, "divisions": [],
                                          "areas": [], "namespaces": []})
            for field, value, prefix in (("divisions", division, "domain"), ("areas", area, "area")):
                if value not in seed[field]:  # type: ignore[operator]
                    seed[field].append(value)  # type: ignore[union-attr]
                    seed["namespaces"].append(f"{prefix}:{slugify(value)}")  # type: ignore[union-attr]
    return list(seeds.values())


def divisions(seeds: List[Dict[str, object]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for s in seeds:
        for d in s["divisions"]:  # type: ignore[union-attr]
            out[d] = out.get(d, 0) + 1  # type: ignore[index]
    return out
