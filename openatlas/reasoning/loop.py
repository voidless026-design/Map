"""Local-model reasoning loop (ATLAS-inspired plan -> execute -> check -> repair).

A clean-room design inspired by itigges22/ATLAS's "put intelligence in the system
around the model" approach: rather than trusting a single LLM answer, we (1) draft a
plan of OSINT functions to run, (2) execute them, (3) let the local model critique the
aggregate against the goal, and (4) optionally propose one repair round. It stays in
AA (Aggregate & Analyze) spirit - a human still selects/approves - and never runs the
autonomous SAR mode.

If Ollama is unavailable, planning falls back to a deterministic heuristic mapping of
target types to relevant functions, so the loop is still useful offline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from openatlas.core.registry import ToolRegistry, load_all_engines
from openatlas.llm import ollama_client
from openatlas.logger import get_logger

log = get_logger("openatlas.reasoning")

# Heuristic fallback: infer target type -> candidate functions.
_HEURISTICS = [
    (re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), ["verify_email_address",
                                                 "check_email_against_breach_data", "get_breached_data"]),
    (re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$"), ["basic_ip_lookup", "core_api_lookups"]),
    (re.compile(r"^https?://"), ["fetch_get_page", "hyperlinks_for_single_url"]),
    (re.compile(r"^[a-zA-Z0-9_.-]+\.[a-zA-Z]{2,}$"), ["find_emails_for_domain"]),
    (re.compile(r"\.(jpg|jpeg|png|webp|gif)$", re.I), ["extract_metadata", "geolocate_local_image",
                                                       "metadata_analysis"]),
]


def infer_plan(target: str) -> List[str]:
    """Deterministic plan when no LLM is available."""
    load_all_engines()
    known = set(ToolRegistry.all_functions())
    for pattern, fns in _HEURISTICS:
        if pattern.search(target.strip()):
            return [f for f in fns if f in known]
    # default: treat as a username
    return [f for f in ["check_usernames", "fetch_about", "search_reddit_posts"] if f in known]


def llm_plan(goal: str, target: str) -> List[str]:
    """Ask the local model to choose functions from the registry for the goal."""
    load_all_engines()
    catalogue = {
        name: (ToolRegistry.spec_for_function(name).description if ToolRegistry.spec_for_function(name) else "")
        for name in sorted(ToolRegistry.all_functions())
    }
    prompt = (
        "You are an OSINT planner. Choose an ordered list of function NAMES from the "
        "catalogue to investigate the target for the goal. Return ONLY a JSON array of names.\n"
        f"Goal: {goal}\nTarget: {target}\nCatalogue: {json.dumps(catalogue)}\n"
    )
    raw = ollama_client.complete(prompt, system="You output strictly a JSON array of strings.")
    if not raw:
        return infer_plan(target)
    try:
        s, e = raw.find("["), raw.rfind("]")
        names = json.loads(raw[s : e + 1])
        known = set(ToolRegistry.all_functions())
        return [n for n in names if n in known] or infer_plan(target)
    except (ValueError, IndexError):
        return infer_plan(target)


def critique(goal: str, results: Dict[str, Any]) -> Dict[str, Any]:
    """Let the local model assess coverage and propose one repair round (best-effort)."""
    if not ollama_client.available():
        return {"assessment": "LLM unavailable; no automated critique.", "next_functions": []}
    prompt = (
        "Given the OSINT goal and the aggregated results, briefly assess whether the goal is "
        "met, list gaps, and propose up to 3 additional function names to run next. "
        'Return JSON: {"assessment":"...","next_functions":["..."]}\n'
        f"Goal: {goal}\nResults: {json.dumps(results, default=str)[:6000]}\n"
    )
    raw = ollama_client.complete(prompt, system="You output strictly valid JSON.")
    if not raw:
        return {"assessment": "no critique produced", "next_functions": []}
    try:
        s, e = raw.find("{"), raw.rfind("}")
        return json.loads(raw[s : e + 1])
    except (ValueError, IndexError):
        return {"assessment": raw[:500], "next_functions": []}


def plan_for(goal: str, target: str) -> List[str]:
    """Public entry: return an ordered function plan (LLM if available, else heuristic)."""
    return llm_plan(goal, target) if ollama_client.available() else infer_plan(target)
