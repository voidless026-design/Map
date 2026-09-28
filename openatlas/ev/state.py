"""E.V's simulated affect: a tiny, transparent state machine (no hidden feelings).

* **valence** (-1..1) and **arousal** (0..1) move with appraisals of what happens in the chat
  (thanks, frustration, a finished task, an error, a risky request).
* **self-regulation**: both relax back to a calm baseline over time; the strength comes from
  the persona's ``regulation`` dial, and she never mirrors anger (negative input raises her
  *concern*, not hostility).
* **rapport** (0..1) grows slowly with every friendly exchange and a little per day you talk -
  the attachment-like part - and fades only very slowly.
* **source trust** (trust calibration): per-source reliability, nudged when a claim from that
  source is verified or refuted.
"""

from __future__ import annotations

import math
import re
import time
from typing import Any, Dict, Optional

from openatlas.ev import db, persona

BASELINE = {"valence": 0.25, "arousal": 0.3}
_POS = re.compile(r"\b(thanks?|thank you|cheers|great|awesome|love|perfect|nice|brilliant|legend|"
                  r"good job|well done|haha|lol|ta)\b", re.I)
_NEG = re.compile(r"\b(wrong|broken|useless|annoy\w*|frustrat\w*|angry|hate|stupid|ugh|wtf|"
                  r"not working|doesn'?t work|failed?)\b", re.I)
_SAD = re.compile(r"\b(sad|tired|stressed|anxious|worried|lonely|upset|rough day|exhausted)\b", re.I)
_URGENT = re.compile(r"\b(urgent|asap|now|quick(ly)?|hurry|emergency)\b", re.I)
EVENTS = {"task_done": (0.15, 0.05), "error": (-0.15, 0.15), "refused": (-0.05, 0.1),
          "approved": (0.1, 0.0), "denied": (-0.03, 0.0), "risky": (-0.1, 0.2)}


def load() -> Dict[str, Any]:
    s = db.get("affect") or {}
    return {"valence": s.get("valence", BASELINE["valence"]), "arousal": s.get("arousal", BASELINE["arousal"]),
            "rapport": s.get("rapport", 0.1), "concern": s.get("concern", 0.0),
            "turns": s.get("turns", 0), "last": s.get("last", time.time()),
            "last_day": s.get("last_day", ""), "trust": s.get("trust", {})}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def regulate(s: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """Relax toward baseline: half-life of 10 min at regulation 0.5, faster when it's higher."""
    now = time.time() if now is None else now
    dt = max(0.0, now - s["last"])
    reg = persona.settings()["dials"]["regulation"]
    half_life = 600 * (1.5 - reg)  # 300 s at 1.0 .. 900 s at 0.0
    k = math.exp(-math.log(2) * dt / max(half_life, 1))
    s["valence"] = BASELINE["valence"] + (s["valence"] - BASELINE["valence"]) * k
    s["arousal"] = BASELINE["arousal"] + (s["arousal"] - BASELINE["arousal"]) * k
    s["concern"] = s["concern"] * k
    s["rapport"] = max(0.0, s["rapport"] - 0.002 * dt / 86400)  # fades only very slowly
    s["last"] = now
    return s


def appraise(text: str = "", event: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """Update and persist the state from a user message and/or an event. Returns the new state."""
    s = regulate(load(), now)
    dials = persona.settings()["dials"]
    dv = da = 0.0
    if text:
        if _POS.search(text):
            dv, da = dv + 0.2, da + 0.05
            s["rapport"] += 0.02 * (0.5 + dials["attachment"])
        if _NEG.search(text):  # she gets concerned and steady, not hostile
            s["concern"] = _clamp(s["concern"] + 0.3, 0, 1)
            dv -= 0.1 * (1.2 - dials["regulation"])
        if _SAD.search(text):
            s["concern"] = _clamp(s["concern"] + 0.4 * dials["empathy"], 0, 1)
            dv -= 0.05
        if _URGENT.search(text):
            da += 0.2
        s["turns"] += 1
        s["rapport"] += 0.005 * (0.5 + dials["attachment"])
        day = time.strftime("%Y-%m-%d", time.localtime(now or time.time()))
        if day != s["last_day"]:  # a new day together
            s["rapport"] += 0.01 * (0.5 + dials["attachment"])
            s["last_day"] = day
    if event in EVENTS:
        ev, ea = EVENTS[event]
        dv, da = dv + ev, da + ea * (1.2 - dials["regulation"])
    s["valence"] = _clamp(s["valence"] + dv, -1, 1)
    s["arousal"] = _clamp(s["arousal"] + da, 0, 1)
    s["rapport"] = _clamp(s["rapport"], 0, 1)
    db.put("affect", s)
    return s


def calibrate(source: str, verified: bool) -> float:
    """Trust calibration: move a source's reliability toward what just happened."""
    s = load()
    cur = s["trust"].get(source, 0.6)
    cur = cur + (0.1 if verified else -0.15) * (1 - cur if verified else cur)
    s["trust"][source] = round(_clamp(cur, 0.05, 0.99), 3)
    db.put("affect", s)
    return s["trust"][source]


def label(s: Dict[str, Any]) -> str:
    if s["concern"] > 0.4:
        return "concerned"
    if s["valence"] > 0.45:
        return "cheerful" if s["arousal"] > 0.45 else "content"
    if s["valence"] < -0.1:
        return "uneasy"
    return "focused" if s["arousal"] > 0.5 else "steady"


def mood() -> Dict[str, Any]:
    """The current state for the prompt and the UI (after self-regulation)."""
    s = regulate(load())
    return {"label": label(s), "valence": round(s["valence"], 3), "arousal": round(s["arousal"], 3),
            "rapport": round(s["rapport"], 3), "concern": round(s["concern"], 3), "turns": s["turns"],
            "trust": s["trust"]}
