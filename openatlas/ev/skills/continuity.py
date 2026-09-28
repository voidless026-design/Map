"""Context Continuity: what E.V remembers about you, across conversations - always visible,
editable and forgettable."""

from __future__ import annotations

from typing import Any, Dict

from openatlas.ev import memory
from openatlas.ev.tools import tool


@tool("remember", kind="read", skill="Context Continuity",
      description="Remember a fact or preference the person shared (only when they want you to).",
      params={"fact": {"type": "string"}}, required=["fact"])
def remember(fact: str) -> Dict[str, Any]:
    f = memory.remember(fact, source="told to E.V")
    return {"remembered": f.get("text", fact), "id": f.get("id")}


@tool("recall", kind="read", skill="Context Continuity",
      description="Look up what you remember about the person and earlier conversations on a topic.",
      params={"query": {"type": "string"}}, required=["query"])
def recall(query: str) -> Dict[str, Any]:
    words = [w for w in query.lower().split() if len(w) > 2]
    facts = [f["text"] for f in memory.facts() if not words or any(w in f["text"].lower() for w in words)]
    past = memory.search(query, 5)
    return {"facts": facts[:15], "earlier": [{"when": m["created"], "who": m["role"], "said": m["content"][:300]}
                                              for m in past]}


@tool("forget", kind="read", skill="Context Continuity",
      description="Forget remembered facts matching these words (or a fact id).",
      params={"what": {"type": "string"}}, required=["what"])
def forget(what: str) -> Dict[str, Any]:
    gone = memory.forget(what)
    return {"forgotten": [f["text"] for f in gone]}
