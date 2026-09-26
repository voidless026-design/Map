"""Rendering helpers for --show-all-functions and --show-api-services.

These read from the live registry (and ``config.API_SERVICES``) so output stays in
sync with what is actually implemented.
"""

from __future__ import annotations

from typing import List

from openatlas.config import API_SERVICES
from openatlas.core.registry import ToolRegistry, load_all_engines


def all_functions_text() -> str:
    load_all_engines()
    lines: List[str] = []
    for common_name, engine in sorted(ToolRegistry.engines().items()):
        lines.append(f"\n[{engine.abbrev or '--'}] {common_name} - {engine.description}")
        for fname in engine.function_names():
            spec = engine.specs.get(fname)
            desc = spec.description if spec else ""
            flags = []
            if spec and spec.needs_llm:
                flags.append("LLM")
            if spec and spec.scrapes_web:
                flags.append("web/robots")
            elif spec and spec.network:
                flags.append("net")
            tag = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"    - {fname}{tag}: {desc}")
    return "\n".join(lines).strip()


def api_services_text() -> str:
    lines = ["Backends in use (all FREE / keyless / local - no paid API keys):", ""]
    width = max(len(s["service"]) for s in API_SERVICES)
    for s in API_SERVICES:
        lines.append(f"  {s['service']:<{width}}  replaces {s['replaces']:<22}  key: {s['key']}")
    lines.append("")
    lines.append("Excluded by policy: OathNet stealer-log retrieval (stolen credentials).")
    return "\n".join(lines)
