"""Decision Support: a weighted options x criteria matrix, a risk read-out and a sensitivity
check ("would the answer change if I cared a bit more about X?"), then a recommendation."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from openatlas.ev import persona
from openatlas.ev.tools import tool

_LOWER_BETTER = re.compile(r"\b(cost|price|risk|effort|time|complexity|latency|noise|danger|debt)\b", re.I)


def matrix(options: List[str], criteria: List[Dict[str, Any]],
           scores: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    crit = []
    for c in criteria:
        name = str(c.get("name") if isinstance(c, dict) else c)
        w = float(c.get("weight", 1) if isinstance(c, dict) else 1)
        lower = c.get("lower_is_better") if isinstance(c, dict) else None
        crit.append({"name": name, "weight": max(w, 0.0),
                     "lower_is_better": bool(_LOWER_BETTER.search(name)) if lower is None else bool(lower)})
    wsum = sum(c["weight"] for c in crit) or 1.0

    def totals(weights: List[float]) -> Dict[str, float]:
        ws = sum(weights) or 1.0
        out = {}
        for o in options:
            s = 0.0
            for c, w in zip(crit, weights):
                v = float((scores.get(o) or {}).get(c["name"], 5))
                v = max(0.0, min(10.0, v))
                s += w * ((10 - v) if c["lower_is_better"] else v)
            out[o] = round(s / ws, 2)
        return out

    base = totals([c["weight"] for c in crit])
    ranked = sorted(base, key=lambda o: -base[o])
    winner = ranked[0] if ranked else None
    flips = []
    for i, c in enumerate(crit):  # sensitivity: +/-25% on each weight
        for f in (0.75, 1.25):
            ws = [cc["weight"] * (f if j == i else 1) for j, cc in enumerate(crit)]
            t = totals(ws)
            alt = max(t, key=t.get) if t else None
            if alt != winner:
                flips.append(f"{'more' if f > 1 else 'less'} weight on '{c['name']}' makes {alt} win")
    margin = round(base[winner] - base[ranked[1]], 2) if len(ranked) > 1 else None
    risk_c = [c["name"] for c in crit if re.search(r"risk|danger", c["name"], re.I)]
    risk = {o: (scores.get(o) or {}).get(risk_c[0]) for o in options} if risk_c else {}
    caution = persona.settings()["dials"]["risk"]
    confidence = "high" if not flips and (margin or 0) >= 1 else "medium" if not flips or (margin or 0) >= 0.5 else "low"
    note = ""
    if risk and winner is not None and risk.get(winner) is not None and float(risk[winner]) >= 7 and caution >= 0.5:
        safer = min((o for o in options if risk.get(o) is not None), key=lambda o: float(risk[o]))
        note = f"{winner} scores best but carries high risk ({risk[winner]}/10); {safer} is the safer choice."
    return {"card": "decision", "criteria": crit, "totals": base, "ranking": ranked, "winner": winner,
            "margin": margin, "sensitivity": flips[:6], "confidence": confidence, "risk_note": note,
            "weights_normalised": {c["name"]: round(c["weight"] / wsum, 3) for c in crit}}


@tool("decision_matrix", kind="read", skill="Decision Support",
      description="Compare options against weighted criteria (scores 0-10 per option per criterion; cost/risk/"
                  "effort count lower-is-better) and recommend one, with a sensitivity check.",
      params={"question": {"type": "string"},
              "options": {"type": "array", "items": {"type": "string"}},
              "criteria": {"type": "array", "items": {"type": "object", "properties": {
                  "name": {"type": "string"}, "weight": {"type": "number"}}}},
              "scores": {"type": "object", "description": "{option: {criterion: 0-10}}"}},
      required=["question", "options", "criteria"])
def decision_matrix(question: str, options: List[str], criteria: List[Any],
                    scores: Optional[Dict[str, Dict[str, float]]] = None) -> Dict[str, Any]:
    options = [str(o) for o in options][:8]
    if len(options) < 2:
        return {"ok": False, "error": "give at least two options to compare"}
    out = matrix(options, criteria or [{"name": "overall", "weight": 1}], scores or {})
    out["question"] = question
    if not scores:
        out["needs_scores"] = True
    return out
