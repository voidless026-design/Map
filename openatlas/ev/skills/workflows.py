"""Workflow Automation: named routines of fixed steps on a schedule, run by the brain daemon.

Approving a routine approves exactly its steps and schedule; changing either means approving
again. Only whitelisted OpenAtlas actions can be steps, and every run is logged.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any, Callable, Dict, List, Optional

from openatlas.ev import db
from openatlas.ev.tools import tool


def _brain_ingest(arg: str = "") -> str:
    import asyncio

    from openatlas.kb import ingest

    n = int(arg or 20)
    done = asyncio.run(ingest.run(max_tasks=max(1, min(n, 500)), idle_exit=True))
    return f"learned: {done}"


def _library_resume(arg: str = "") -> str:
    from openatlas.kb import library

    ids = library.resume_all()
    library.start_background()
    return f"resumed {len(ids)} download(s)"


def _search_eval(arg: str = "") -> str:
    from openatlas.kb import evaluate

    r = evaluate.eval_brain(sample=int(arg or 100))
    return f"search quality ok={r['ok']} P@1={r['metrics'].get('p_at_1')}"


def _doctor(arg: str = "") -> str:
    from openatlas.skills import doctor

    res = doctor.run_all()
    bad = [c["tool"] for c in res["checks"] if c["status"] == "fail"]
    return "doctor: all tools verified" if not bad else f"doctor: failing - {', '.join(bad)}"


def _research_digest(arg: str = "") -> str:
    from openatlas.ev.skills.research import search_brain

    q = arg or "latest"
    hits = search_brain(q, 5)["sources"]
    notes = db.ev_dir() / "notes"
    notes.mkdir(exist_ok=True)
    f = notes / f"digest-{_dt.date.today().isoformat()}-{re.sub(r'[^a-z0-9]+', '-', q.lower())[:30]}.md"
    f.write_text(f"# Digest: {q}\n\n" + "\n".join(f"- **{h['title']}** - {h['text'][:200]}…" for h in hits))
    return f"digest saved: {f}"


ACTIONS: Dict[str, Callable[[str], str]] = {
    "brain_ingest": _brain_ingest, "library_resume": _library_resume, "search_eval": _search_eval,
    "doctor": _doctor, "research_digest": _research_digest}
_SCHED = re.compile(r"^(hourly|daily( \d{1,2}:\d{2})?|weekly (mon|tue|wed|thu|fri|sat|sun)( \d{1,2}:\d{2})?|manual)$", re.I)


def _norm_steps(steps: List[Any]) -> List[Dict[str, str]]:
    out = []
    for s in steps or []:
        if isinstance(s, str):
            action, _, arg = s.partition(":")
        else:
            action, arg = str(s.get("action", "")), str(s.get("arg", ""))
        action = action.strip()
        if action not in ACTIONS:
            raise ValueError(f"'{action}' isn't an allowed step - use one of {', '.join(ACTIONS)}")
        out.append({"action": action, "arg": arg.strip()[:200]})
    if not out:
        raise ValueError("a routine needs at least one step")
    return out


def routines() -> List[Dict[str, Any]]:
    out = db.rows("SELECT * FROM routines ORDER BY name")
    for r in out:
        r["steps"], r["log"] = json.loads(r["steps"]), json.loads(r["log"])[-10:]
    return out


def is_due(r: Dict[str, Any], now: Optional[_dt.datetime] = None) -> bool:
    now = now or _dt.datetime.now()
    sched = (r["schedule"] or "manual").lower()
    last = _dt.datetime.fromisoformat(r["last_run"]) if r.get("last_run") else None
    if sched == "manual" or not r["approved"]:
        return False
    if sched == "hourly":
        return not last or now - last >= _dt.timedelta(hours=1)
    parts = sched.split()
    hh, mm = (int(x) for x in (parts[-1].split(":") if ":" in parts[-1] else ("9", "0")))
    if parts[0] == "daily":
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        wd = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(parts[1])
        slot = (now - _dt.timedelta(days=(now.weekday() - wd) % 7)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now >= slot and (not last or last < slot)


def execute(name: str) -> Dict[str, Any]:
    r = db.one("SELECT * FROM routines WHERE name=?", (name,))
    if not r:
        raise KeyError(name)
    steps, log = json.loads(r["steps"]), json.loads(r["log"])
    entry: Dict[str, Any] = {"at": db.now(), "steps": []}
    for s in steps:
        try:
            entry["steps"].append({**s, "ok": True, "out": ACTIONS[s["action"]](s["arg"])[:300]})
        except Exception as exc:
            entry["steps"].append({**s, "ok": False, "out": f"{type(exc).__name__}: {exc}"[:300]})
    log = (log + [entry])[-50:]
    with db.connect() as con:
        con.execute("UPDATE routines SET last_run=?, log=? WHERE name=?",
                    (_dt.datetime.now().isoformat(timespec="seconds"), json.dumps(log), name))
    return entry


def run_due(now: Optional[_dt.datetime] = None) -> List[str]:
    """Run approved routines whose time has come. Each slot is claimed atomically first, so
    Atlas and the brain service running side by side never run a routine twice."""
    ran = []
    for r in routines():
        if not is_due(r, now):
            continue
        stamp = (now or _dt.datetime.now()).isoformat(timespec="seconds")
        with db.connect() as con:
            claimed = con.execute("UPDATE routines SET last_run=? WHERE name=? AND last_run IS ?",
                                  (stamp, r["name"], r["last_run"])).rowcount
        if claimed:
            execute(r["name"])
            ran.append(r["name"])
    return ran


_sched: Optional[Any] = None


def start_scheduler(every: float = 60.0) -> bool:
    """A tiny background ticker (started by `openatlas serve` and the brain service)."""
    import threading
    import time

    global _sched
    if _sched and _sched.is_alive():
        return False

    def tick() -> None:
        while True:
            try:
                run_due()
            except Exception:  # a broken routine must never take the app down
                pass
            time.sleep(every)
    _sched = threading.Thread(target=tick, name="ev-routines", daemon=True)
    _sched.start()
    return True


@tool("create_routine", kind="command", skill="Workflow Automation",
      description="Create (or replace) a named routine of OpenAtlas steps on a schedule. Steps: "
                  "brain_ingest:<n>, library_resume, search_eval:<n>, doctor, research_digest:<topic>. "
                  "Schedule: hourly | daily HH:MM | weekly mon HH:MM | manual. Needs approval.",
      params={"name": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
              "schedule": {"type": "string"}}, required=["name", "steps"])
def create_routine(name: str, steps: List[Any], schedule: str = "manual") -> Dict[str, Any]:
    sched = (schedule or "manual").strip().lower()
    if not _SCHED.match(sched):
        raise ValueError("schedule must be hourly, daily HH:MM, weekly mon HH:MM or manual")
    clean = _norm_steps(steps)
    with db.connect() as con:
        con.execute("INSERT INTO routines(name, steps, schedule, approved, created) VALUES (?,?,?,1,?) "
                    "ON CONFLICT(name) DO UPDATE SET steps=excluded.steps, schedule=excluded.schedule, approved=1",
                    (name[:80], json.dumps(clean), sched, db.now()))
    return {"routine": name, "steps": clean, "schedule": sched, "approved": True}


@tool("list_routines", kind="read", skill="Workflow Automation",
      description="List routines with their schedule, steps and last runs.")
def list_routines() -> Dict[str, Any]:
    return {"routines": routines(), "allowed_steps": list(ACTIONS)}


@tool("run_routine", kind="command", skill="Workflow Automation",
      description="Run a routine now (needs approval).", params={"name": {"type": "string"}}, required=["name"])
def run_routine(name: str) -> Dict[str, Any]:
    return {"routine": name, "run": execute(name)}
