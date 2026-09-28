"""E.V's conversation loop: persona + memory -> local model (streaming, native tool calls) ->
skills -> automatic quality check -> saved turn.

Events yielded to the UI / voice pipeline (dicts with a ``type``):
``start``, ``mood``, ``token``, ``tool``, ``approval``, ``card``, ``qa``, ``notice``, ``done``.

Without a tool-capable model a keyword router calls the same skills; without Ollama at all
E.V still answers from her skills (brain, documents, plans, decisions) and says how to
bring the local model up.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from openatlas.ev import memory, persona, state, tools
from openatlas.ev.skills import documents, qa
from openatlas.llm import ollama_client

MAX_ROUNDS = 4
TOOLS_NOTE = ("Use your tools when they help: search_brain / read_article / web_search for facts "
              "(then cite results as [n]), read_document / list_documents for the person's files, "
              "make_plan for multi-step goals, decision_matrix for choices, plan_project / "
              "create_project for new projects, create_routine / list_routines / run_routine for "
              "automation, remember / recall / forget for memory, check_claims to double-check. "
              "Don't invent tool results. Tools marked as needing approval become a card the person "
              "approves - tell them what you've queued and why.")


def _args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def _brief(result: Dict[str, Any], limit: int = 2500) -> str:
    """Tool result as the model sees it (sources are numbered by the caller)."""
    slim = {k: v for k, v in result.items() if k not in ("sources", "card")}
    return json.dumps(slim, default=str)[:limit]


def _number_sources(result: Dict[str, Any], sources: List[Dict[str, Any]]) -> str:
    lines = []
    for s in result.get("sources") or []:
        sources.append(s)
        lines.append(f"[{len(sources)}] {s.get('title', '')}: {str(s.get('text', ''))[:700]}")
    return "\n".join(lines)


# ------------------------------------------------------------------ keyword router (no tool calling)
_DOC = re.compile(r"\b(document|pdf|docx|file|report|paper|contract|my notes)\b", re.I)
_PLAN = re.compile(r"\b(plan|steps?|roadmap|checklist|how (do|should) i|break (it|this) down)\b", re.I)
_DECIDE = re.compile(r"\b(should i|which (is|one)|decide|decision|compare|pros and cons|better)\b|\bvs\.?\b", re.I)
_ROUTINE = re.compile(r"\b(routines?|automat\w*|every (day|morning|night|week)|schedule)\b", re.I)
_PROJECT = re.compile(r"\b(new project|set ?up (a|my) project|scaffold|start a project)\b", re.I)
_CHECK = re.compile(r"\b(fact[- ]?check|verify|is (it|this) true|double[- ]check)\b", re.I)
_QUESTION = re.compile(r"\?|^(what|who|when|where|why|how|tell me|explain|define|describe)\b", re.I)
_SMALLTALK = re.compile(r"^\s*(hi|hey|hello|g'?day|yo|good (morning|afternoon|evening|night)|how are you|"
                        r"how'?s it going|thanks?|thank you|cheers|bye|see ya)\b", re.I)


def route(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Which skills a message needs, when the model can't call tools itself."""
    calls: List[Tuple[str, Dict[str, Any]]] = []
    path = documents.maybe_path(text)
    if path or _DOC.search(text):
        if path:
            calls.append(("read_document", {"path": path, "question": text}))
        else:
            calls.append(("list_documents", {}))
    if _PROJECT.search(text):
        name = re.sub(r".*(project|scaffold)\s*(called|named|for)?\s*", "", text, flags=re.I).strip(" .?!") or "new project"
        calls.append(("plan_project", {"name": name[:60], "goal": text}))
    elif _ROUTINE.search(text):
        calls.append(("list_routines", {}))
    elif _DECIDE.search(text):
        opts = [o.strip(" ?.") for o in re.split(r"\s+(?:or|vs\.?|versus)\s+", re.sub(r"^.*?(between|:)\s*", "", text, flags=re.I)) if o.strip(" ?.")]
        if len(opts) >= 2:
            calls.append(("decision_matrix", {"question": text, "options": opts[:5],
                                              "criteria": [{"name": "benefit", "weight": 2},
                                                           {"name": "cost", "weight": 1},
                                                           {"name": "risk", "weight": 1}]}))
    elif _PLAN.search(text):
        calls.append(("make_plan", {"goal": text}))
    if _CHECK.search(text):
        calls.append(("check_claims", {"text": text}))
    if not calls and _QUESTION.search(text) and not _SMALLTALK.match(text):
        calls.append(("search_brain", {"query": text}))
    return calls


def _offline_reply(text: str, results: List[Tuple[str, Dict[str, Any]]], why: str) -> str:
    """A useful answer without a language model, built from what the skills returned."""
    name = persona.settings()["user_name"]
    if _SMALLTALK.match(text) and not results:
        return (f"G'day{', ' + name if name else ''}! I'm here, though I'm running on my skills alone until "
                "the local model is up - ask me about the brain, your documents, a plan or a decision.")
    parts = []
    for tool_name, r in results:
        if r.get("pending"):
            parts.append(f"I've queued **{tool_name}** for your approval - have a look at the card.")
        elif not r.get("ok", True):
            parts.append(f"{tool_name} didn't work: {r.get('error')}")
        elif tool_name == "search_brain":
            srcs = r.get("sources") or []
            if srcs:
                parts.append("Here's what my brain has on that:\n" + "\n".join(
                    f"- {s['title']} [{i + 1}]: {s['text'][:220].strip()}…" for i, s in enumerate(srcs[:4])))
            else:
                parts.append("I don't have anything on that in my brain yet - I've queued it to learn.")
        elif tool_name == "read_document":
            ps = r.get("passages") or []
            parts.append(f"From **{r['document']}** ({r['pages']} pages):\n" + ("\n".join(
                f"- p.{p['page']}: {p['text'][:240]}…" for p in ps) if ps else r.get("opening", "")[:600]))
        elif tool_name == "list_documents":
            docs = r.get("documents") or []
            parts.append("Documents I can read:\n" + "\n".join(f"- {d['name']}" for d in docs[:10])
                         if docs else f"I can't see any documents yet. Drop one into the chat or put it in {r.get('folders')}.")
        elif r.get("card") == "plan":
            parts.append(f"Here's a plan for that - tick things off as you go ({len(r['plan']['steps'])} steps).")
        elif r.get("card") == "decision":
            parts.append("I've set up the comparison. " + ("Give each option a score out of 10 per criterion "
                         "and I'll work out the winner." if r.get("needs_scores") else f"On these numbers, **{r['winner']}** comes out ahead."))
        elif r.get("card") == "project":
            parts.append(f"Here's a layout for **{r['name']}** - say the word and I'll create it (you'll get an approval card).")
        elif tool_name == "list_routines":
            rs = r.get("routines") or []
            parts.append("Your routines: " + (", ".join(f"{x['name']} ({x['schedule']})" for x in rs) if rs
                                              else "none yet. Tell me what to run and when, and I'll set one up for your approval."))
        elif r.get("card") == "qa":
            c = r["counts"]
            parts.append(f"Checked {r['checked']} claim(s): {c['supported']} supported, {c['unsupported']} unsupported, "
                         f"{c['unverified']} unverified.")
    if not parts:
        parts.append("I'm here, but I can't think in full sentences until my local model is running.")
    return "\n\n".join(parts)


# ------------------------------------------------------------------ the loop
def respond(conv_id: Optional[int], text: str, *, stop: Optional[threading.Event] = None,
            voice: bool = False) -> Iterator[Dict[str, Any]]:
    t0 = time.monotonic()
    text = (text or "").strip()
    conv_id = conv_id or memory.new_conversation()
    memory.add(conv_id, "user", text, {"voice": voice})
    yield {"type": "start", "conv_id": conv_id}
    sources: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"tools": [], "cards": [], "approvals": []}
    final = ""

    def finish(answer: str, extra: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        nonlocal final
        final = answer
        if sources and answer:
            report = qa.check(answer, sources, use_model=not voice)
            if report["checked"]:
                meta["qa"] = report
                for c in report["claims"]:
                    if c["source"] and c["verdict"] != "unverified":
                        state.calibrate(c["source"][:60], c["verdict"] == "supported")
                yield {"type": "qa", **report}
        meta["sources"] = [{k: s.get(k) for k in ("title", "url", "why")} for s in sources]
        meta.update(extra or {})
        meta["ms_total"] = round((time.monotonic() - t0) * 1000)
        mood = state.appraise(event="task_done" if meta["tools"] else "")
        meta["mood"] = state.label(mood)
        mid = memory.add(conv_id, "assistant", answer, meta)
        if len([m for m in memory.messages(conv_id, 400) if m["role"] == "user"]) % 8 == 0:
            memory.refresh_summary(conv_id)
        yield {"type": "done", "conv_id": conv_id, "message_id": mid, "text": answer, "meta": meta}

    # 1. moral decision-making: refuse clearly, offer a better route
    blocked = tools.ethics_screen(text)
    if blocked:
        state.appraise(text, event="refused")
        answer = (f"I'm going to pass on that one - it would mean {blocked}, and that's not something I'll do "
                  "even for you. If you're checking your *own* exposure, I can run a self-audit of what's "
                  "public about you instead, or help you lock your accounts down.")
        yield {"type": "token", "text": answer}
        yield from finish(answer, {"refused": blocked})
        return

    # 2. explicit memory commands work even with no model
    cmd = memory.explicit_memory_command(text)
    mood = state.appraise(text)
    yield {"type": "mood", **state.mood()}
    if cmd:
        if cmd["action"] == "remember":
            answer = f"Noted - I'll remember that: “{cmd['fact'].get('text', '')}” (you can ask me to forget it any time)."
        else:
            gone = cmd["forgotten"]
            answer = ("Done, I've forgotten: " + "; ".join(f["text"] for f in gone)) if gone else \
                "I didn't have anything like that stored - nothing to forget."
        yield {"type": "token", "text": answer}
        yield from finish(answer)
        return

    conv = memory.conversation(conv_id) or {}
    system = persona.system_prompt(mood={**state.mood(), "label": state.label(mood)},
                                   facts=memory.fact_lines(), summary=conv.get("summary", ""),
                                   tools_note=TOOLS_NOTE)
    if voice:
        system += "\n\nThis reply will be spoken aloud: 1-3 short sentences, no lists, no markdown, no [n] markers."
    history = memory.recent_for_model(conv_id)
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system}, *history]

    def run_calls(calls: List[Tuple[str, Dict[str, Any]]]) -> Iterator[Dict[str, Any]]:
        for name, args in calls:
            result = tools.run(name, args, conv_id=conv_id)
            t = tools.REGISTRY.get(name)
            meta["tools"].append({"name": name, "ok": bool(result.get("ok")), "pending": bool(result.get("pending"))})
            if result.get("pending"):
                meta["approvals"].append(result["approval"]["id"])
                yield {"type": "approval", **result["approval"]}
            else:
                yield {"type": "tool", "name": name, "skill": t.skill if t else "", "kind": t.kind if t else "",
                       "args": args, "ok": bool(result.get("ok")), "error": result.get("error"),
                       "summary": _brief(result, 400)}
                card = result.get("card")
                if card and card != "qa":
                    meta["cards"].append(result)
                    yield {"type": "card", **result}
            result["_name"] = name
            yield {"type": "_result", "name": name, "result": result}

    diag = ollama_client.diagnose()
    if not diag["ok"]:  # no local model: still be useful, and say how to fix it
        results = []
        for ev in run_calls(route(text)):
            if ev["type"] == "_result":
                results.append((ev["name"], ev["result"]))
                _number_sources(ev["result"], sources)
            else:
                yield ev
        answer = _offline_reply(text, results, diag["message"])
        yield {"type": "notice", "level": "warn", "text": diag["message"]}
        yield {"type": "token", "text": answer}
        yield from finish(answer, {"offline": True})
        return

    use_tools = True
    first_token = None
    for _round in range(MAX_ROUNDS):
        buf: List[str] = []
        calls: List[Tuple[str, Dict[str, Any]]] = []
        try:
            for ev in ollama_client.stream_chat(messages, tools=tools.schemas() if use_tools else None, stop=stop):
                if ev["type"] == "token":
                    if first_token is None:
                        first_token = round((time.monotonic() - t0) * 1000)
                    buf.append(ev["text"])
                    yield ev
                elif ev["type"] == "tool_calls":
                    for c in ev["calls"]:
                        fn = c.get("function") or {}
                        calls.append((fn.get("name", ""), _args(fn.get("arguments"))))
                elif ev["type"] == "done" and ev.get("cancelled"):
                    yield from finish("".join(buf), {"interrupted": True, "model": ev.get("model")})
                    return
        except ollama_client.LLMUnavailable as exc:
            if str(exc).startswith("tools_unsupported") and use_tools:
                use_tools = False  # this model can't call tools: route in Python, then just talk
                pre = []
                for ev in run_calls(route(text)):
                    if ev["type"] == "_result":
                        pre.append(_number_sources(ev["result"], sources) or _brief(ev["result"]))
                    else:
                        yield ev
                if pre:
                    messages.append({"role": "system", "content": "Results from your skills (cite as [n]):\n" + "\n".join(pre)})
                continue
            yield {"type": "notice", "level": "warn", "text": str(exc)}
            answer = "".join(buf) or f"Sorry - my local model stopped answering: {exc}"
            yield from finish(answer, {"error": str(exc)})
            return
        if not calls:
            yield from finish("".join(buf), {"ms_first_token": first_token, "model": diag.get("model")})
            return
        messages.append({"role": "assistant", "content": "".join(buf),
                         "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]})
        for ev in run_calls(calls):
            if ev["type"] != "_result":
                yield ev
                continue
            r = ev["result"]
            if r.get("pending"):
                content = f"Queued for the person's approval (card #{r['approval']['id']}); not run yet."
            else:
                numbered = _number_sources(r, sources)
                content = (numbered + "\n" if numbered else "") + _brief(r)
            messages.append({"role": "tool", "content": content, "tool_name": ev["name"]})
    yield from finish("".join(buf) or "I went round in circles there - could you rephrase?",
                      {"ms_first_token": first_token, "model": diag.get("model")})


def reply_text(conv_id: Optional[int], text: str, **kw: Any) -> Dict[str, Any]:
    """Run a turn to completion (CLI / tests). Returns the ``done`` event plus collected events."""
    events = [e for e in respond(conv_id, text, **kw) if e["type"] != "_result"]
    done = next(e for e in reversed(events) if e["type"] == "done")
    return {**done, "events": events}
