"""Answer a question from the brain, with citations - never from thin air.

With a local LLM: the model sees only the retrieved passages and must cite them as [n];
citations that don't point at a retrieved passage are removed. Without an LLM: the most
relevant passages are returned as-is (extractive answer).
"""

from __future__ import annotations

import re
from typing import Any, Dict

from openatlas.kb import ingest, retrieve


def ask(question: str, k: int = 6) -> Dict[str, Any]:
    ingest.boost(question)  # learn more about what you ask about
    hits = retrieve.search(question, k=k)
    if not hits:
        return {"mode": "none", "answer": "The brain has nothing on this yet. It has been queued "
                "for learning - try again once ingestion has caught up.", "citations": []}
    from openatlas.llm import ollama_client

    if ollama_client.available():
        passages = "\n\n".join(f"[{i + 1}] {h['title']}: {h['text'][:900]}" for i, h in enumerate(hits))
        answer = ollama_client.complete(
            f"Passages:\n{passages}\n\nQuestion: {question}\n\nAnswer using ONLY the passages. "
            f"Cite every claim as [n]. If the passages do not answer it, say so.",
            system="You are a precise research assistant that never invents facts.", max_tokens=600)
        if answer:
            used = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 1 <= int(n) <= len(hits)})
            answer = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(hits) else "",
                            answer)
            return {"mode": "llm", "answer": answer.strip(),
                    "citations": [{"n": n, **_cite(hits[n - 1])} for n in used] or
                                 [{"n": i + 1, **_cite(h)} for i, h in enumerate(hits[:3])]}
    return {"mode": "extractive",
            "answer": "\n\n".join(f"[{i + 1}] {h['snippet']}" for i, h in enumerate(hits[:3])),
            "citations": [{"n": i + 1, **_cite(h)} for i, h in enumerate(hits[:3])]}


def _cite(h: Dict[str, Any]) -> Dict[str, Any]:
    return {"title": h["title"], "url": h["url"], "license": h["license"], "source": h["source"],
            "why": h.get("why", ""), "score": h.get("score")}
