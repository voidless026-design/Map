"""OpenAtlas web app: JSON API + Server-Sent Events + static single-page UI.

Security defaults: binds to 127.0.0.1; refuses any other bind address unless
OPENATLAS_TOKEN is set, in which case every /api call must send it in the
``X-OpenAtlas-Token`` header. Host headers are checked on loopback (DNS-rebinding guard).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from openatlas import catalog as _catalog
from openatlas.logger import get_logger
from openatlas.version import __version__

log = get_logger("openatlas.web")
STATIC = Path(__file__).parent / "static"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class InvestigateIn(BaseModel):
    target: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=3, max_length=500)
    filter: str = ""
    sources: Optional[List[str]] = None
    type: Optional[str] = None
    name: str = ""


class PlanIn(BaseModel):
    target: str = Field(min_length=1, max_length=500)
    purpose: str = ""
    type: Optional[str] = None


class RunIn(BaseModel):
    value: str = Field(min_length=1, max_length=2000)
    purpose: str = ""
    args: Dict[str, Any] = {}


class AskIn(BaseModel):
    q: str = Field(min_length=2, max_length=1000)


class BrainPlanIn(BaseModel):
    max_tier: int = 3


# --------------------------------------------------------------------------- #
# live case event hub (in-memory; finished cases are also in the database)
# --------------------------------------------------------------------------- #
class CaseHub:
    def __init__(self) -> None:
        self.events: Dict[str, List[Dict[str, Any]]] = {}
        self.done: Dict[str, bool] = {}
        self.cond = asyncio.Condition()

    async def emit(self, case_id: str, event: Dict[str, Any]) -> None:
        async with self.cond:
            self.events.setdefault(case_id, []).append(event)
            if event.get("type") in ("done", "error"):
                self.done[case_id] = True
            self.cond.notify_all()

    async def stream(self, case_id: str):  # type: ignore[no-untyped-def]
        i = 0
        while True:
            async with self.cond:
                evs = self.events.get(case_id, [])
                while i >= len(evs) and not self.done.get(case_id):
                    try:
                        await asyncio.wait_for(self.cond.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        break
                    evs = self.events.get(case_id, [])
                batch, i = evs[i:], len(evs)
                finished = self.done.get(case_id, False)
            if batch:
                for ev in batch:
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            else:
                yield ": keep-alive\n\n"
            if finished and i >= len(self.events.get(case_id, [])):
                return


def create_app(token: Optional[str] = None, loopback: bool = True) -> FastAPI:
    app = FastAPI(title="OpenAtlas", version=__version__, docs_url=None, redoc_url=None)
    hub = CaseHub()
    tasks: Dict[str, asyncio.Task] = {}

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if loopback:
            host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
            if host and host not in LOOPBACK and host != "testserver":
                return PlainTextResponse("bad host", status_code=400)
        if token and request.url.path.startswith("/api/"):
            if not secrets.compare_digest(request.headers.get("x-openatlas-token", ""), token):
                return JSONResponse({"detail": "token required"}, status_code=401)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    # ---------------- pages ----------------
    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/viz/brain", response_class=HTMLResponse)
    async def viz_brain() -> HTMLResponse:
        """The knowledge base in the ATSMATRIX visualizer - reload to watch it grow."""
        from openatlas.utils import knowledge_graph

        graph = await asyncio.to_thread(knowledge_graph.build_graph_from_brain)
        return HTMLResponse(knowledge_graph.inline_html(graph))

    @app.get("/viz/{case_id}", response_class=HTMLResponse)
    async def viz(case_id: str) -> HTMLResponse:
        from openatlas.core.database import db_funcs
        from openatlas.utils import knowledge_graph

        case = db_funcs.get_case(case_id)
        if not case or not case.get("report"):
            raise HTTPException(404, "case not found or still running")
        graph = knowledge_graph.build_graph_from_case(case["report"])
        return HTMLResponse(knowledge_graph.inline_html(graph))

    # ---------------- system ----------------
    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        from openatlas.llm import ollama_client
        from openatlas.runtime import profiles
        from openatlas.runtime.resources import detect, process_rss_mb

        def _collect() -> Dict[str, Any]:
            return {"version": __version__, "profile": profiles.active().to_dict(),
                    "hardware": detect().to_dict(), "llm": ollama_client.status(),
                    "gpu": ollama_client.gpu_report(), "rss_mb": process_rss_mb(),
                    "search_backend": _search_backend()}

        return await asyncio.to_thread(_collect)

    @app.get("/api/catalog")
    async def catalog() -> Dict[str, Any]:
        return _catalog.catalog()

    @app.get("/api/detect")
    async def detect(q: str) -> Dict[str, Any]:
        from openatlas.investigate.detect import detect as _detect
        from openatlas.investigate.sources import for_target

        t = _detect(q)
        return {"target": t.to_dict(), "sources": [s.id for s in for_target(t.type)]}

    # ---------------- investigations ----------------
    async def _start(body: InvestigateIn) -> str:
        from openatlas.investigate.pipeline import run_investigation

        case_id = secrets.token_hex(6)

        async def job() -> None:
            loop = asyncio.get_running_loop()

            def emit(ev: Dict[str, Any]) -> None:
                loop.create_task(hub.emit(case_id, ev))

            try:
                await run_investigation(body.target, purpose=body.purpose, name=body.name,
                                        forced_type=body.type or None, filter_id=body.filter,
                                        source_ids=body.sources or None, emit=emit, case_id=case_id)
            except Exception as exc:  # surface to the UI instead of dying silently
                log.exception("case %s failed", case_id)
                await hub.emit(case_id, {"type": "error", "message": f"{type(exc).__name__}: {exc}"})

        tasks[case_id] = asyncio.create_task(job())
        return case_id

    @app.post("/api/plan")
    async def plan(body: PlanIn) -> Dict[str, Any]:
        """ATLAS loop, step 1: propose sources for the target (a human then presses Run)."""
        from openatlas.reasoning import loop

        return await asyncio.to_thread(loop.plan_case, body.target, body.purpose, body.type or "")

    @app.get("/api/cases/{case_id}/check")
    async def check(case_id: str) -> Dict[str, Any]:
        """ATLAS loop, check + repair: assess a finished case and propose one repair round."""
        from openatlas.core.database import db_funcs
        from openatlas.reasoning import loop

        c = await asyncio.to_thread(db_funcs.get_case, case_id)
        if not c or not c.get("report", {}).get("summary"):
            raise HTTPException(404, "case not found or still running")
        return await asyncio.to_thread(loop.check_case, c["report"])

    @app.post("/api/investigate")
    async def investigate(body: InvestigateIn) -> Dict[str, Any]:
        return {"case_id": await _start(body)}

    @app.get("/api/cases/{case_id}/events")
    async def events(case_id: str) -> StreamingResponse:
        if case_id not in hub.events and case_id not in tasks:
            raise HTTPException(404, "unknown or finished case - use /api/cases/{id}")
        return StreamingResponse(hub.stream(case_id), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/cases/{case_id}/cancel")
    async def cancel(case_id: str) -> Dict[str, Any]:
        t = tasks.get(case_id)
        if t and not t.done():
            t.cancel()
            await hub.emit(case_id, {"type": "error", "message": "cancelled"})
            return {"cancelled": True}
        return {"cancelled": False}

    @app.get("/api/cases")
    async def cases() -> List[Dict[str, Any]]:
        from openatlas.core.database import db_funcs

        return await asyncio.to_thread(db_funcs.list_cases)

    @app.get("/api/cases/{case_id}")
    async def case(case_id: str) -> Dict[str, Any]:
        from openatlas.core.database import db_funcs

        c = await asyncio.to_thread(db_funcs.get_case, case_id)
        if not c:
            raise HTTPException(404, "case not found")
        return c

    @app.get("/api/cases/{case_id}/markdown", response_class=PlainTextResponse)
    async def case_md(case_id: str) -> str:
        from openatlas.core.database import db_funcs
        from openatlas.investigate.report import to_markdown

        c = await asyncio.to_thread(db_funcs.get_case, case_id)
        if not c or not c.get("report"):
            raise HTTPException(404, "case not found")
        return to_markdown(c["report"])

    # ---------------- single actions ----------------
    @app.post("/api/run/{slug}")
    async def run(slug: str, body: RunIn) -> Dict[str, Any]:
        action = _catalog.find(slug)
        if not action:
            raise HTTPException(404, f"unknown action '{slug}'")
        if action["kind"] == "source":
            if not body.purpose.strip():
                raise HTTPException(422, "purpose is required")
            cid = await _start(InvestigateIn(target=body.value, purpose=body.purpose,
                                             sources=[slug]))
            return {"case_id": cid}
        result = await asyncio.to_thread(_catalog.run_tool, action, body.value, body.args)
        return {"result": result}

    # ---------------- brain ----------------
    @app.get("/api/brain")
    async def brain() -> Dict[str, Any]:
        from openatlas.kb import daemon, ingest

        p = await asyncio.to_thread(ingest.progress)
        p["in_process"] = daemon.running_in_process()
        return p

    @app.post("/api/brain/{action}")
    async def brain_action(action: str, body: Optional[BrainPlanIn] = None) -> Dict[str, Any]:
        from openatlas.kb import daemon, ingest, store, taxonomy

        if action == "plan":
            added = await asyncio.to_thread(ingest.plan, taxonomy.parse(),
                                            (body or BrainPlanIn()).max_tier)
            return {"planned": added}
        if action == "start":
            if not ingest.next_task():
                await asyncio.to_thread(ingest.plan, taxonomy.parse(), 3)
            store.set_meta("paused", False)
            return {"started": daemon.start_background()}
        if action == "pause":
            store.set_meta("paused", True)
            return {"paused": True}
        if action == "resume":
            store.set_meta("paused", False)
            return {"paused": False}
        raise HTTPException(404, "unknown brain action")

    @app.get("/api/kb/search")
    async def kb_search(q: str, k: int = 8) -> List[Dict[str, Any]]:
        from openatlas.kb import retrieve

        hits = await asyncio.to_thread(retrieve.search, q, min(k, 20))
        return [{k2: v for k2, v in h.items() if k2 != "text"} for h in hits]

    @app.post("/api/ask")
    async def ask(body: AskIn) -> Dict[str, Any]:
        from openatlas.kb import ask as _ask

        return await asyncio.to_thread(_ask.ask, body.q)

    # ---------------- skills ----------------
    @app.get("/api/skills")
    async def skills() -> List[Dict[str, Any]]:
        from openatlas.skills import registry

        return await asyncio.to_thread(registry.list_skills)

    @app.post("/api/skills/check")
    async def skills_check() -> Dict[str, Any]:
        from openatlas.skills import doctor

        return await asyncio.to_thread(doctor.run_all)

    return app


def _search_backend() -> str:
    from openatlas.investigate.sources.websearch import backend

    return backend()


def serve(host: str = "127.0.0.1", port: int = 8600, open_browser: bool = True,
          brain: bool = False) -> int:
    import uvicorn

    token = os.getenv("OPENATLAS_TOKEN") or None
    loop = host in LOOPBACK
    if not loop and not token:
        print("Refusing to listen on a non-loopback address without OPENATLAS_TOKEN set.\n"
              "Set a long random token, e.g.  export OPENATLAS_TOKEN=$(openssl rand -hex 24)\n"
              "and prefer a private network (WireGuard / Tailscale) over exposing it publicly.")
        return 2
    if brain:
        from openatlas.kb import daemon

        daemon.start_background()
    url = f"http://{'127.0.0.1' if loop else host}:{port}/"
    print(f"OpenAtlas is running at {url}  (Ctrl+C to stop)")
    if open_browser and loop:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(create_app(token=token, loopback=loop), host=host, port=port, log_level="warning")
    return 0
