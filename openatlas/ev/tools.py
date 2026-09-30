"""E.V's tools (her nine skills), the approval gate, and the pre-action risk simulation.

Every tool has a *kind*:

* ``read``    - reads the brain, your allowed documents, E.V's own memory: runs straight away.
* ``network`` - fetches from the public web: needs your approval.
* ``write``   - writes files: needs your approval.
* ``command`` - runs an OpenAtlas command or routine: needs your approval.

A tool call that needs approval becomes a pending card with a risk appraisal (the "risk and
fear simulation" trait) until you approve or deny it. Nothing else can run it.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openatlas.ev import db, persona

AUTO_KINDS = ("read",)
KINDS = ("read", "network", "write", "command")


@dataclass
class Tool:
    name: str
    kind: str
    skill: str
    description: str
    params: Dict[str, Any]
    fn: Callable[..., Dict[str, Any]]
    required: List[str] = field(default_factory=list)

    def schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": f"[{self.skill}] {self.description}",
            "parameters": {"type": "object", "properties": self.params, "required": self.required}}}


REGISTRY: Dict[str, Tool] = {}


def tool(name: str, *, kind: str, skill: str, description: str,
         params: Optional[Dict[str, Any]] = None, required: Optional[List[str]] = None) -> Callable:
    assert kind in KINDS, kind

    def deco(fn: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
        REGISTRY[name] = Tool(name, kind, skill, description, params or {}, fn, required or [])
        return fn
    return deco


def load_skills() -> Dict[str, Tool]:
    """Import the skill modules so their tools register (idempotent)."""
    from openatlas.ev.skills import (  # noqa: F401
        continuity,
        decisions,
        documents,
        engineering,
        planning,
        project,
        qa,
        research,
        workflows,
    )
    return REGISTRY


def schemas() -> List[Dict[str, Any]]:
    return [t.schema() for t in load_skills().values()]


def skills() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for t in load_skills().values():
        out.setdefault(t.skill, []).append(t.name)
    return out


# ------------------------------------------------------------------ ethics (moral decision-making)
_FORBIDDEN = [
    (re.compile(r"\b(bypass|get around|crack|break)\b.{0,30}\b(paywall|captcha|login|password|2fa|drm)\b", re.I),
     "getting around a login, paywall, CAPTCHA or password"),
    (re.compile(r"\b(stealer logs?|combo ?lists?|leaked passwords? of|dump(ed)? credentials)\b", re.I),
     "retrieving stolen credentials"),
    (re.compile(r"\b(stalk|track down|find (where|the home address of)|dox+)\b", re.I),
     "tracking or doxxing a private person"),
    (re.compile(r"\b(ddos|flood (the|their) server|deploy ransomware|write (a )?malware)\b", re.I),
     "attacking systems"),
]


def ethics_screen(text: str) -> Optional[str]:
    """The reason E.V won't do this, or None. (Investigating your *own* footprint is fine.)"""
    for pat, why in _FORBIDDEN:
        if pat.search(text or "") and not re.search(r"\b(my own|myself|self-audit)\b", text, re.I):
            return why
    return None


# ------------------------------------------------------------------ risk simulation
def assess_risk(t: Tool, args: Dict[str, Any]) -> Dict[str, Any]:
    """A quick 'what could go wrong' before an action; caution scales with the risk dial."""
    caution = persona.settings()["dials"]["risk"]
    concerns: List[str] = []
    score = {"read": 0.05, "network": 0.3, "write": 0.45, "command": 0.5}[t.kind]
    reversible = t.kind in ("read", "network")
    worst = {"read": "nothing changes", "network": "your IP address is seen by the sites queried",
             "write": "files are created or changed on your disk",
             "command": "OpenAtlas runs a job that uses CPU, disk and network for a while"}[t.kind]
    target = str(args.get("path") or args.get("folder") or "")
    if target:
        p = Path(target).expanduser()
        if p.exists() and t.kind == "write":
            concerns.append(f"{p} already exists - existing files won't be overwritten")
            score += 0.1
        if not str(p.resolve()).startswith(str(Path.home())):
            concerns.append("outside your home folder")
            score += 0.25
            reversible = False
    if t.kind == "network":
        concerns.append("public web only; no logins or cookies are sent")
    if t.kind == "command" and args.get("schedule"):
        concerns.append(f"will repeat on a schedule ({args['schedule']}) until you remove it")
        score += 0.1
    score = min(1.0, score * (0.6 + 0.8 * caution))
    level = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
    feeling = {"low": "Looks safe to me.", "medium": "I'm fairly comfortable with this, but have a look first.",
               "high": "This one makes me a bit nervous - please check it carefully."}[level]
    return {"level": level, "score": round(score, 2), "reversible": reversible, "worst_case": worst,
            "concerns": concerns, "feeling": feeling}


# ------------------------------------------------------------------ running + the approval gate
def run(name: str, args: Dict[str, Any], *, conv_id: int = 0, approved: bool = False) -> Dict[str, Any]:
    """Run a tool. ``read`` tools run; anything else returns a pending approval unless
    ``approved`` came from :func:`approve` (the only caller that sets it)."""
    t = load_skills().get(name)
    if t is None:
        return {"ok": False, "error": f"no tool called {name}"}
    blocked = ethics_screen(json.dumps(args))
    if blocked:
        return {"ok": False, "refused": True, "error": f"I won't help with {blocked}."}
    if t.kind not in AUTO_KINDS and not approved:
        return {"ok": False, "pending": True, "approval": request_approval(t, args, conv_id)}
    kwargs = {k: v for k, v in (args or {}).items() if k in t.params}
    if "_conv_id" in inspect.signature(t.fn).parameters:
        kwargs["_conv_id"] = conv_id
    try:
        out = t.fn(**kwargs)
    except TypeError as exc:
        return {"ok": False, "error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # a tool failure is reported, never crashes the chat
        return {"ok": False, "error": f"{name} failed: {type(exc).__name__}: {exc}"}
    out.setdefault("ok", True)
    return out


def request_approval(t: Tool, args: Dict[str, Any], conv_id: int) -> Dict[str, Any]:
    risk = assess_risk(t, args)
    with db.connect() as con:
        cur = con.execute("INSERT INTO approvals(conv_id, tool, args, kind, risk, created) VALUES (?,?,?,?,?,?)",
                          (conv_id, t.name, json.dumps(args), t.kind, json.dumps(risk), db.now()))
        aid = int(cur.lastrowid)
    return approval(aid) or {}


def approval(aid: int) -> Optional[Dict[str, Any]]:
    a = db.one("SELECT * FROM approvals WHERE id=?", (aid,))
    if a:
        a["args"], a["risk"] = json.loads(a["args"]), json.loads(a["risk"])
        a["result"] = json.loads(a["result"]) if a["result"] else None
        t = REGISTRY.get(a["tool"])
        a["skill"], a["description"] = (t.skill, t.description) if t else ("", "")
    return a


def pending(conv_id: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = "SELECT id FROM approvals WHERE status='pending'" + (" AND conv_id=?" if conv_id else "")
    return [approval(r["id"]) for r in db.rows(sql, (conv_id,) if conv_id else ())]


def decide(aid: int, approve: bool) -> Dict[str, Any]:
    """Approve (run it now) or deny a pending action. Each approval runs exactly once."""
    a = approval(aid)
    if a is None:
        raise KeyError(aid)
    if a["status"] != "pending":
        return a
    from openatlas.ev import state

    if not approve:
        with db.connect() as con:
            con.execute("UPDATE approvals SET status='denied', decided=? WHERE id=?", (db.now(), aid))
        state.appraise(event="denied")
        return approval(aid) or {}
    with db.connect() as con:  # claim it first so a double click can't run it twice
        claimed = con.execute("UPDATE approvals SET status='running', decided=? WHERE id=? AND status='pending'",
                              (db.now(), aid)).rowcount
    if not claimed:
        return approval(aid) or {}
    result = run(a["tool"], a["args"], conv_id=a["conv_id"], approved=True)
    with db.connect() as con:
        con.execute("UPDATE approvals SET status=?, result=? WHERE id=?",
                    ("done" if result.get("ok") else "failed", json.dumps(result, default=str)[:20000], aid))
    state.appraise(event="approved" if result.get("ok") else "error")
    return approval(aid) or {}
