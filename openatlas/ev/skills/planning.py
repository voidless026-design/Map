"""Interactive Planning: an editable checklist in the chat. E.V drafts the steps, you tick,
edit, reorder or add; she keeps track of what's left (and nudges you back to it)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openatlas.ev import db
from openatlas.ev.tools import tool

_OSINT = re.compile(r"\b(investigat\w*|look ?up|osint|footprint|who owns|username|e-?mail address)\b", re.I)


def _default_steps(goal: str) -> List[str]:
    if _OSINT.search(goal):
        return ["State the purpose (self-audit, due diligence…) and confirm the target is fair game",
                "Auto-plan the sources for the target (Investigate → Auto-plan)",
                "Run the case and let osint-verify label every finding",
                "Review confirmed vs unverified findings; drop anything you can't source",
                "Write up the case report and file it"]
    return [f"Pin down what 'done' looks like for: {goal}",
            "Gather what you already have (documents, notes, the brain)",
            "Break the work into the first three concrete actions",
            "Do the first action and check the result",
            "Review, adjust the plan, and schedule the rest"]


def _save(plan_id: Optional[int], conv_id: int, goal: str, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    with db.connect() as con:
        if plan_id:
            con.execute("UPDATE plans SET goal=?, steps=?, updated=? WHERE id=?",
                        (goal, json.dumps(steps), db.now(), plan_id))
        else:
            plan_id = int(con.execute("INSERT INTO plans(conv_id, goal, steps, created, updated) VALUES (?,?,?,?,?)",
                                      (conv_id, goal, json.dumps(steps), db.now(), db.now())).lastrowid)
    return get(plan_id) or {}


def get(plan_id: int) -> Optional[Dict[str, Any]]:
    p = db.one("SELECT * FROM plans WHERE id=?", (plan_id,))
    if p:
        p["steps"] = json.loads(p["steps"])
        p["done"] = sum(1 for s in p["steps"] if s.get("done"))
    return p


def open_plans() -> List[Dict[str, Any]]:
    out = [get(r["id"]) for r in db.rows("SELECT id FROM plans ORDER BY updated DESC LIMIT 20")]
    return [p for p in out if p and p["done"] < len(p["steps"])]


def edit(plan_id: int, *, toggle: Optional[int] = None, text: Optional[Dict[str, Any]] = None,
         add: Optional[str] = None, remove: Optional[int] = None, move: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    p = get(plan_id)
    if not p:
        raise KeyError(plan_id)
    steps = p["steps"]
    if toggle is not None and 0 <= toggle < len(steps):
        steps[toggle]["done"] = not steps[toggle].get("done")
    if text and 0 <= int(text.get("index", -1)) < len(steps):
        steps[int(text["index"])]["text"] = str(text.get("text", ""))[:300]
    if add:
        steps.append({"text": add[:300], "done": False})
    if remove is not None and 0 <= remove < len(steps):
        steps.pop(remove)
    if move:
        i, j = int(move.get("from", -1)), int(move.get("to", -1))
        if 0 <= i < len(steps) and 0 <= j < len(steps):
            steps.insert(j, steps.pop(i))
    return _save(plan_id, p["conv_id"], p["goal"], steps)


@tool("make_plan", kind="read", skill="Interactive Planning",
      description="Draft an editable step-by-step plan (checklist card) for a goal. Give your own steps "
                  "when you can; otherwise a sensible default is drafted.",
      params={"goal": {"type": "string"},
              "steps": {"type": "array", "items": {"type": "string"}, "description": "3-8 concrete steps"}},
      required=["goal"])
def make_plan(goal: str, steps: Optional[List[str]] = None, _conv_id: int = 0) -> Dict[str, Any]:
    items = [s for s in (steps or []) if isinstance(s, str) and s.strip()][:12] or _default_steps(goal)
    plan = _save(None, _conv_id, goal[:200], [{"text": s.strip()[:300], "done": False} for s in items])
    return {"card": "plan", "plan": plan}
