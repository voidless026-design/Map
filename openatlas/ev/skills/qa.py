"""Quality Assurance: check E.V's factual answers against the sources she used, claim by claim.

This is the step that replaces checking an AI's answer by hand. Each factual sentence gets:

* **supported**   - the cited (or best-matching) source passage contains it,
* **unsupported** - it cites a source that doesn't say it, or a number/name in it isn't there,
* **unverified**  - nothing she looked at speaks to it (general knowledge, opinion, or a guess).

Lexical entailment runs everywhere (no model needed); when the local model is up, borderline
claims get a second opinion from it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from openatlas.ev.tools import tool

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{2,}|\d[\d,.]*")
_NUM = re.compile(r"\b\d[\d,.]*\b")
_CITE = re.compile(r"\[(\d{1,2})\]")
_NOT_FACTUAL = re.compile(r"^(hi|hey|g'day|sure|no worries|cheers|thanks|okay|ok|let me|i can|i'll|"
                          r"would you|do you|want me|shall i|here'?s|i reckon|i think|maybe|perhaps)\b", re.I)
_NEG = re.compile(r"\b(not|no|never|none|neither|cannot|can't|isn't|wasn't|didn't|doesn't)\b", re.I)


def _stems(text: str) -> set:
    from openatlas.kb.retrieve import STOPWORDS, _stem

    return {_stem(w.lower()) for w in _WORD.findall(text) if w.lower() not in STOPWORDS and not _NUM.fullmatch(w)}


def _nums(text: str) -> set:
    return {n.rstrip(".,").replace(",", "") for n in _NUM.findall(text)}


def claims(answer: str) -> List[str]:
    """Factual sentences worth checking (greetings, questions and hedges are skipped)."""
    out = []
    for s in _SENT.split(re.sub(r"\s+", " ", answer or "").strip()):
        bare = _CITE.sub("", s).strip(" -•*")
        if len(bare.split()) < 5 or bare.endswith("?") or _NOT_FACTUAL.match(bare):
            continue
        out.append(s.strip())
    return out


def _judge(claim: str, passage: str) -> Optional[bool]:
    from openatlas.llm import ollama_client

    if not ollama_client.available():
        return None
    got = ollama_client.complete(
        f"Passage:\n{passage[:1500]}\n\nClaim: {claim}\n\nDoes the passage support the claim? "
        "Answer with one word: yes, no, or unclear.", max_tokens=3, temperature=0)
    g = (got or "").strip().lower()
    return True if g.startswith("yes") else False if g.startswith("no") else None


def check(answer: str, sources: List[Dict[str, Any]], *, use_model: bool = True) -> Dict[str, Any]:
    """Label every factual claim in ``answer`` against ``sources`` ([{title, text, url}] in
    citation order, so ``[1]`` is ``sources[0]``)."""
    results = []
    for c in claims(answer):
        cited = [int(n) - 1 for n in _CITE.findall(c) if 0 < int(n) <= len(sources)]
        body = _CITE.sub("", c)
        cw, cn = _stems(body), _nums(body)
        best, best_i, best_cov = None, None, 0.0
        for i, s in enumerate(sources):
            if cited and i not in cited:
                continue
            sw = _stems(s.get("text", "") + " " + s.get("title", ""))
            cov = len(cw & sw) / len(cw) if cw else 0.0
            if cov > best_cov:
                best, best_i, best_cov = s, i, cov
        missing_nums = sorted(cn - _nums(best.get("text", "") + " " + best.get("title", ""))) if best else sorted(cn)
        neg_flip = bool(best) and bool(_NEG.search(body)) != bool(_NEG.search(best.get("text", "")[:2000])) \
            and best_cov >= 0.6
        if best is None or (best_cov < 0.3 and not cited):
            verdict, why = "unverified", "no source I used speaks to this"
        elif missing_nums:
            verdict, why = "unsupported", f"{', '.join(missing_nums)} isn't in the source"
        elif best_cov >= 0.6 and not neg_flip:
            verdict, why = "supported", f"{round(best_cov * 100)}% of its key words are in the source"
        elif neg_flip:
            verdict, why = "unsupported", "the source says the opposite (negation differs)"
        else:
            verdict, why = ("unsupported" if cited else "unverified"), \
                f"only {round(best_cov * 100)}% of its key words are in the source"
            if use_model and best is not None and best_cov >= 0.3:
                j = _judge(body, best.get("text", ""))
                if j is not None:
                    verdict, why = ("supported", "the local model confirms the source says this") if j else \
                        ("unsupported", "the local model says the source doesn't support this")
        results.append({"claim": c, "verdict": verdict, "why": why,
                        "source": (best or {}).get("title") if best_i is not None else None,
                        "source_index": (best_i + 1) if best_i is not None else None})
    counts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("supported", "unsupported", "unverified")}
    return {"card": "qa", "claims": results, "counts": counts,
            "ok": counts["unsupported"] == 0, "checked": len(results)}


@tool("check_claims", kind="read", skill="Quality Assurance",
      description="Check each factual claim in a text against given sources (or the brain) and label it "
                  "supported / unsupported / unverified.",
      params={"text": {"type": "string"},
              "sources": {"type": "array", "items": {"type": "object"}, "description": "[{title, text, url}]"}},
      required=["text"])
def check_claims(text: str, sources: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if not sources:
        from openatlas.ev.skills.research import search_brain

        sources = search_brain(" ".join(list(_stems(text))[:12]) or text[:200], 6)["sources"]
    return check(text, sources)
