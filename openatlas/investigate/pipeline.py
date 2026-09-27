"""Run an investigation end to end and stream progress events.

Stages: detect target -> run sources in parallel (bounded, per-source timeouts, overall
deadline) -> open top result pages -> automatic verification -> correlate -> optional
local-LLM summary -> save the case (DB + brain).

``emit`` receives dict events: ``start``, ``source_start``, ``evidence``, ``source_done``,
``stage``, ``summary``, ``done``. The GUI streams these over Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from openatlas.investigate import correlate as _correlate
from openatlas.investigate import reader, sources
from openatlas.investigate import verify as _verify
from openatlas.investigate.detect import detect
from openatlas.investigate.models import Evidence, SourceResult, Target, now_iso
from openatlas.logger import get_logger
from openatlas.net.client import Net

log = get_logger("openatlas.investigate")

Emit = Callable[[Dict[str, Any]], None]


def _noop(_: Dict[str, Any]) -> None:
    pass


async def run_investigation(
    raw: str,
    *,
    purpose: str,
    name: str = "",
    forced_type: Optional[str] = None,
    filter_id: str = "",
    source_ids: Optional[List[str]] = None,
    deadline: float = 150.0,
    read_pages: int = 6,
    summarize: Optional[bool] = None,
    emit: Emit = _noop,
    case_id: Optional[str] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """Investigate ``raw`` and return the case report dict."""
    if not purpose or not purpose.strip():
        raise ValueError("a purpose is required for every investigation (see ETHICS.md)")
    t0 = time.monotonic()
    case_id = case_id or uuid.uuid4().hex[:12]
    target = detect(raw, forced_type)
    specs = _select(target, filter_id, source_ids)
    name = name or f"{target.type}: {target.value}"

    if persist:
        from openatlas.core.database import db_funcs

        # Off the event loop: a slow disk must not stall the GUI's live stream.
        await asyncio.to_thread(db_funcs.create_case, case_id, name=name, purpose=purpose,
                                target=target.value, target_type=target.type)

    emit({"type": "start", "case_id": case_id, "target": target.to_dict(),
          "sources": [s.to_dict() for s in specs]})

    evidence: List[Evidence] = []
    results: List[SourceResult] = []

    async with Net() as net:
        async def run_one(spec: sources.SourceSpec) -> SourceResult:
            emit({"type": "source_start", "source": spec.id, "title": spec.title})
            try:
                res = await asyncio.wait_for(spec.fn(target, net), timeout=spec.timeout)
            except asyncio.TimeoutError:
                res = SourceResult(spec.id, ok=False, searched=spec.description,
                                   error=f"timed out after {spec.timeout:.0f}s")
            except Exception as exc:  # a broken source must never sink the case
                log.exception("source %s failed", spec.id)
                res = SourceResult(spec.id, ok=False, searched=spec.description,
                                   error=f"{type(exc).__name__}: {exc}")
            for ev in res.evidence:
                emit({"type": "evidence", "evidence": ev.to_dict()})
            emit({"type": "source_done", "result": res.to_dict()})
            return res

        tasks = [asyncio.create_task(run_one(s)) for s in specs]
        done, pending = await asyncio.wait(tasks, timeout=max(5.0, deadline * 0.7))
        for p in pending:
            p.cancel()
        for d in done:
            if not d.cancelled() and d.exception() is None:
                res = d.result()
                results.append(res)
                evidence.extend(res.evidence)
        if pending:
            emit({"type": "stage", "stage": "deadline",
                  "message": f"{len(pending)} source(s) stopped at the time limit"})

        remaining = deadline - (time.monotonic() - t0)
        if read_pages and remaining > 5 and any(e.source == "web-search" for e in evidence):
            emit({"type": "stage", "stage": "reading", "message": "Opening top result pages"})
            try:
                new = await asyncio.wait_for(
                    reader.read_pages(net, target, evidence, limit=read_pages),
                    timeout=remaining * 0.6)
            except asyncio.TimeoutError:
                new = []
            for ev in new:
                emit({"type": "evidence", "evidence": ev.to_dict()})
            evidence.extend(new)

        remaining = deadline - (time.monotonic() - t0)
        emit({"type": "stage", "stage": "verifying", "message": "Re-checking findings"})
        try:
            await asyncio.wait_for(_verify.verify_all(net, target, evidence),
                                   timeout=max(5.0, remaining))
        except asyncio.TimeoutError:
            pass

    entities = _correlate.correlate(evidence)
    evidence = _dedupe(evidence)
    evidence.sort(key=lambda e: ({True: 0, None: 1, False: 2}[e.verified], -e.confidence))

    summary_text = None
    if _want_summary(summarize) and evidence:
        emit({"type": "stage", "stage": "summarizing", "message": "Local AI summary"})
        summary_text = await asyncio.to_thread(_summarize, target, evidence)

    report = _report(case_id, name, purpose, target, results, evidence, entities,
                     summary_text, time.monotonic() - t0)
    if persist:
        from openatlas.core.database import db_funcs

        await asyncio.to_thread(db_funcs.finish_case, case_id, report)
        await asyncio.to_thread(_to_brain, report)
    emit({"type": "done", "case_id": case_id, "summary": report["summary"]})
    return report


def _select(target: Target, filter_id: str, source_ids: Optional[List[str]]) -> List[sources.SourceSpec]:
    applicable = sources.for_target(target.type)
    if source_ids:
        wanted = set(source_ids)
        return [s for s in applicable if s.id in wanted]
    if filter_id:
        return [s for s in applicable if filter_id in s.filters and s.default]
    return [s for s in applicable if s.default]


def _dedupe(evidence: List[Evidence]) -> List[Evidence]:
    seen, out = set(), []
    for e in evidence:
        if e.id not in seen:
            seen.add(e.id)
            out.append(e)
    return out


def _want_summary(flag: Optional[bool]) -> bool:
    if flag is not None:
        return flag
    from openatlas.runtime import profiles

    return profiles.active().summarize_search


def _summarize(target: Target, evidence: List[Evidence]) -> Optional[str]:
    from openatlas.llm import ollama_client

    lines = [f"[{i + 1}] ({e.status}) {e.title} - {e.snippet[:200]} <{e.url or 'no link'}>"
             for i, e in enumerate(evidence[:25])]
    prompt = (f"Target: {target.value} ({target.type}).\nFindings:\n" + "\n".join(lines) +
              "\n\nWrite a short, neutral summary of what the public record shows. Cite findings "
              "as [n]. Treat 'unverified' findings as uncertain and say so. Do not speculate "
              "beyond the findings.")
    return ollama_client.complete(prompt, system="You are a careful OSINT analyst.",
                                  max_tokens=500)


def _report(case_id: str, name: str, purpose: str, target: Target, results: List[SourceResult],
            evidence: List[Evidence], entities: List[Dict[str, Any]], summary: Optional[str],
            elapsed: float) -> Dict[str, Any]:
    counts = {"confirmed": 0, "refuted": 0, "unverified": 0}
    for e in evidence:
        counts[e.status] += 1
    return {
        "case_id": case_id, "name": name, "purpose": purpose, "target": target.to_dict(),
        "finished_at": now_iso(), "elapsed_s": round(elapsed, 1),
        "summary": {**counts, "findings": len(evidence), "entities": len(entities),
                    "sources_ok": sum(1 for r in results if r.ok),
                    "sources_failed": sum(1 for r in results if not r.ok)},
        "searched": [r.to_dict() for r in results],
        "entities": entities,
        "evidence": [e.to_dict() for e in evidence],
        "ai_summary": summary,
    }


def _to_brain(report: Dict[str, Any]) -> None:
    try:
        from openatlas.kb import store

        store.add_case(report)
    except Exception as exc:  # the brain is optional; never fail a case over it
        log.debug("brain ingest of case skipped: %s", exc)
