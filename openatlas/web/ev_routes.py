"""E.V's HTTP + WebSocket API (loopback, same token guard as the rest of the app)."""

from __future__ import annotations

import asyncio
import json
import secrets
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse


def _post(loop, q, item) -> None:  # type: ignore[no-untyped-def]
    """Hand an event from a worker thread to the async side; fine if the client already left."""
    try:
        loop.call_soon_threadsafe(q.put_nowait, item)
    except RuntimeError:  # event loop closed
        pass


def _sse(ev: Dict[str, Any]) -> str:
    return f"data: {json.dumps(ev, default=str)}\n\n"


def register(app: FastAPI, token: Optional[str] = None) -> None:
    from openatlas.ev import agent, memory, persona, state, tools
    from openatlas.ev.skills import documents, planning, workflows

    @app.post("/api/ev/chat")
    async def ev_chat(body: Dict[str, Any], request: Request) -> StreamingResponse:
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(422, "say something")
        conv_id = int(body["conv_id"]) if body.get("conv_id") else None
        stop = threading.Event()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def work() -> None:
            try:
                for ev in agent.respond(conv_id, text, stop=stop):
                    if ev["type"] != "_result":
                        _post(loop, q, ev)
            except Exception as exc:  # never leave the page hanging
                _post(loop, q, {"type": "notice", "level": "error",
                                                         "text": f"{type(exc).__name__}: {exc}"})
            finally:
                _post(loop, q, None)

        threading.Thread(target=work, name="ev-turn", daemon=True).start()

        async def gen():  # type: ignore[no-untyped-def]
            try:
                while True:
                    ev = await q.get()
                    if ev is None:
                        return
                    yield _sse(ev)
                    if await request.is_disconnected():
                        stop.set()
                        return
            finally:
                stop.set()
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/ev/conversations")
    async def ev_conversations(q: str = "") -> List[Dict[str, Any]]:
        return await asyncio.to_thread(memory.conversations, 60, q)

    @app.get("/api/ev/conversations/{conv_id}")
    async def ev_conversation(conv_id: int) -> Dict[str, Any]:
        conv = await asyncio.to_thread(memory.conversation, conv_id)
        if not conv:
            raise HTTPException(404, "no such conversation")
        msgs = await asyncio.to_thread(memory.messages, conv_id)
        for m in msgs:  # refresh approval / plan cards to their current state
            m["meta"]["approvals"] = [tools.approval(a) for a in m["meta"].get("approvals", [])]
            for c in m["meta"].get("cards", []):
                if c.get("card") == "plan":
                    c["plan"] = planning.get(c["plan"]["id"]) or c["plan"]
        return {**conv, "messages": msgs}

    @app.delete("/api/ev/conversations/{conv_id}")
    async def ev_delete(conv_id: int) -> Dict[str, Any]:
        await asyncio.to_thread(memory.delete_conversation, conv_id)
        return {"deleted": conv_id}

    @app.post("/api/ev/approvals/{aid}")
    async def ev_decide(aid: int, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            a = await asyncio.to_thread(tools.decide, aid, bool(body.get("approve")))
        except KeyError as exc:
            raise HTTPException(404, "no such approval") from exc
        if a.get("conv_id"):
            res = a.get("result") or {}
            if a["status"] == "done":
                line = f"Done - {a['tool'].replace('_', ' ')} finished."
                if res.get("folder"):
                    line += f" Created {res['folder']} ({len(res.get('written', []))} files)."
                if res.get("routine"):
                    line += f" Routine '{res['routine']}' is set ({res.get('schedule')})."
                if res.get("sources"):
                    line += " Found: " + "; ".join(s["title"] for s in res["sources"][:5])
            elif a["status"] == "failed":
                line = f"That didn't work: {res.get('error', 'unknown error')}"
            else:
                line = "No worries, I've left that alone."
            await asyncio.to_thread(memory.add, a["conv_id"], "assistant", line, {"approval_result": aid})
            a["message"] = line
        return a

    @app.post("/api/ev/propose")
    async def ev_propose(body: Dict[str, Any]) -> Dict[str, Any]:
        """Queue one tool call from a card (e.g. "Create it…" on a project draft). Anything but a
        read tool becomes a pending approval - this never runs an action by itself."""
        name = str(body.get("tool", ""))
        if name not in tools.load_skills():
            raise HTTPException(404, "no such tool")
        args = body.get("args") if isinstance(body.get("args"), dict) else {}
        conv = int(body["conv_id"]) if body.get("conv_id") else 0
        return await asyncio.to_thread(tools.run, name, args, conv_id=conv)

    @app.get("/api/ev/approvals")
    async def ev_pending() -> List[Dict[str, Any]]:
        return await asyncio.to_thread(tools.pending)

    @app.get("/api/ev/state")
    async def ev_state() -> Dict[str, Any]:
        from openatlas.ev import voice
        from openatlas.llm import ollama_client

        def collect() -> Dict[str, Any]:
            return {"name": "E.V", "mood": state.mood(), "persona": persona.settings(),
                    "traits": [{"key": t.key, "label": t.label, "default": t.default} for t in persona.TRAITS],
                    "llm": ollama_client.diagnose(), "voice": voice.status(), "skills": tools.skills(),
                    "plans": planning.open_plans(), "pending": len(tools.pending()),
                    "facts": memory.facts(), "routines": workflows.routines()}
        return await asyncio.to_thread(collect)

    @app.post("/api/ev/settings")
    async def ev_settings(body: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(persona.update, body)

    @app.post("/api/ev/memory")
    async def ev_remember(body: Dict[str, Any]) -> Dict[str, Any]:
        return await asyncio.to_thread(memory.remember, str(body.get("text", "")), "added in Settings")

    @app.delete("/api/ev/memory/{fact_id}")
    async def ev_forget(fact_id: int) -> Dict[str, Any]:
        gone = await asyncio.to_thread(memory.forget, str(fact_id))
        return {"forgotten": gone}

    @app.patch("/api/ev/plans/{plan_id}")
    async def ev_plan(plan_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(planning.edit, plan_id, toggle=body.get("toggle"), text=body.get("text"),
                                           add=body.get("add"), remove=body.get("remove"), move=body.get("move"))
        except KeyError as exc:
            raise HTTPException(404, "no such plan") from exc

    @app.post("/api/ev/documents")
    async def ev_upload(request: Request, name: str) -> Dict[str, Any]:
        data = await request.body()
        try:
            dest = await asyncio.to_thread(documents.save_upload, name, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"name": dest.name, "path": str(dest), "kb": round(len(data) / 1024)}

    @app.delete("/api/ev/routines/{name}")
    async def ev_routine_delete(name: str) -> Dict[str, Any]:
        from openatlas.ev import db

        with db.connect() as con:
            con.execute("DELETE FROM routines WHERE name=?", (name,))
        return {"deleted": name}

    # ---------------- voice: mic PCM in, E.V's voice out (see openatlas/ev/voice.py) ----------------
    @app.websocket("/ws/ev/voice")
    async def ev_voice(ws: WebSocket) -> None:
        from openatlas.ev import voice

        if token and not secrets.compare_digest(ws.query_params.get("token", ""), token):
            await ws.close(code=4401)
            return
        await ws.accept()
        session = voice.Session(conv_id=int(ws.query_params.get("conv") or 0) or None)
        try:
            await session.run(ws)
        except WebSocketDisconnect:
            pass
        finally:
            session.close()
