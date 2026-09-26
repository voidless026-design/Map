"""Database access layer: engine selection, schema creation, and logging helpers."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from openatlas.config import Config
from openatlas.core.database.models import Base, FunctionRun, Session
from openatlas.logger import get_logger

log = get_logger("openatlas.db")

_ENGINE: Optional[Engine] = None
_SESSIONMAKER: Optional[sessionmaker] = None


def _build_engine() -> Engine:
    backend = (Config.database.backend or "sqlite").lower()
    if backend == "mysql":
        from openatlas.core.database import mysql_setup

        return mysql_setup.make_engine()
    if backend in {"postgres", "postgresql"}:
        from openatlas.core.database import postgres_setup

        return postgres_setup.make_engine()
    from openatlas.core.database import sqlite_setup

    return sqlite_setup.make_engine()


def get_engine() -> Engine:
    global _ENGINE, _SESSIONMAKER
    if _ENGINE is None:
        _ENGINE = _build_engine()
        _SESSIONMAKER = sessionmaker(bind=_ENGINE, future=True)
    return _ENGINE


def init_db() -> None:
    """Create tables if they don't exist."""
    Base.metadata.create_all(get_engine())


def _session() -> OrmSession:
    get_engine()
    assert _SESSIONMAKER is not None
    return _SESSIONMAKER()


def new_session(label: str = "") -> str:
    """Create a new investigation session, returning its session_id."""
    init_db()
    sid = uuid.uuid4().hex[:16]
    with _session() as s:
        s.add(Session(session_id=sid, label=label))
        s.commit()
    log.debug("created investigation session %s", sid)
    return sid


def add_logs_to_database(
    session_id: str,
    function_name: str,
    function_output: Any,
    *,
    engine_name: str = "",
    arguments: Optional[Dict[str, Any]] = None,
    success: bool = True,
) -> None:
    """Persist a function run + its output (best-effort; never breaks the CLI)."""
    try:
        init_db()
        if isinstance(function_output, str):
            out = function_output
        else:
            out = json.dumps(function_output, default=str)
        with _session() as s:
            s.add(
                FunctionRun(
                    session_id=session_id,
                    function_name=function_name,
                    engine_name=engine_name,
                    arguments_json=json.dumps(arguments or {}, default=str),
                    function_output=out,
                    success=1 if success else 0,
                )
            )
            s.commit()
    except Exception as exc:  # logging must never crash an investigation
        log.warning("failed to persist run for %s: %s", function_name, exc)


def get_runs(session_id: str) -> List[Dict[str, Any]]:
    """Return all runs for a session (for report building)."""
    init_db()
    with _session() as s:
        rows = s.execute(
            select(FunctionRun).where(FunctionRun.session_id == session_id).order_by(FunctionRun.id)
        ).scalars().all()
        return [
            {
                "function_name": r.function_name,
                "engine_name": r.engine_name,
                "arguments": json.loads(r.arguments_json or "{}"),
                "output": r.function_output,
                "success": bool(r.success),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Return a session's metadata, or None if it doesn't exist."""
    init_db()
    with _session() as s:
        row = s.execute(
            select(Session).where(Session.session_id == session_id)
        ).scalars().first()
        if row is None:
            return None
        return {
            "session_id": row.session_id,
            "label": row.label,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def latest_session_id() -> Optional[str]:
    """Return the most recently created session_id, or None if there are none."""
    init_db()
    with _session() as s:
        row = s.execute(select(Session).order_by(Session.id.desc())).scalars().first()
        return row.session_id if row else None


def reset_for_tests(url: str = "sqlite:///:memory:") -> None:  # pragma: no cover
    """Point the layer at an in-memory DB (used by the test-suite)."""
    global _ENGINE, _SESSIONMAKER
    from sqlalchemy import create_engine

    _ENGINE = create_engine(url, future=True)
    _SESSIONMAKER = sessionmaker(bind=_ENGINE, future=True)
    Base.metadata.create_all(_ENGINE)


# --------------------------------------------------------------------------- #
# v2 investigation cases
# --------------------------------------------------------------------------- #
def create_case(case_id: str, *, name: str, purpose: str, target: str, target_type: str) -> None:
    from openatlas.core.database.models import Case

    init_db()
    with _session() as s:
        s.add(Case(case_id=case_id, name=name, purpose=purpose, target=target,
                   target_type=target_type, status="running"))
        s.commit()


def finish_case(case_id: str, report: Dict[str, Any], status: str = "done") -> None:
    import datetime as _dt

    from openatlas.core.database.models import Case, CaseEvidence

    init_db()
    with _session() as s:
        case = s.execute(select(Case).where(Case.case_id == case_id)).scalars().first()
        if case is None:
            return
        case.status = status
        case.report_json = json.dumps(report, default=str)
        case.finished_at = _dt.datetime.now(_dt.timezone.utc)
        for ev in report.get("evidence", []):
            s.add(CaseEvidence(
                case_id=case_id, evidence_id=ev.get("id", ""), source=ev.get("source", ""),
                kind=ev.get("kind", ""), entity_type=ev.get("entity_type") or "",
                entity_value=(ev.get("entity_value") or "")[:500], url=ev.get("url") or "",
                status=ev.get("status", "unverified"),
                confidence=int(round(float(ev.get("confidence", 0)) * 100)),
                evidence_json=json.dumps(ev, default=str)))
        s.commit()


def list_cases(limit: int = 50) -> List[Dict[str, Any]]:
    from openatlas.core.database.models import Case

    init_db()
    with _session() as s:
        rows = s.execute(select(Case).order_by(Case.id.desc()).limit(limit)).scalars().all()
        out = []
        for c in rows:
            summary = json.loads(c.report_json or "{}").get("summary", {})
            out.append({"case_id": c.case_id, "name": c.name, "purpose": c.purpose,
                        "target": c.target, "target_type": c.target_type, "status": c.status,
                        "created_at": c.created_at.isoformat() if c.created_at else None,
                        "summary": summary})
        return out


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    from openatlas.core.database.models import Case

    init_db()
    with _session() as s:
        c = s.execute(select(Case).where(Case.case_id == case_id)).scalars().first()
        if c is None:
            return None
        return {"case_id": c.case_id, "name": c.name, "purpose": c.purpose, "target": c.target,
                "target_type": c.target_type, "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "report": json.loads(c.report_json or "{}")}


def seen_before(entity_type: str, entity_value: str, exclude_case: str = "") -> List[Dict[str, Any]]:
    """Other cases where the same entity was found ("have we seen this email before?")."""
    from openatlas.core.database.models import CaseEvidence

    init_db()
    with _session() as s:
        rows = s.execute(select(CaseEvidence).where(
            CaseEvidence.entity_type == entity_type,
            CaseEvidence.entity_value == entity_value.lower(),
            CaseEvidence.case_id != exclude_case)).scalars().all()
        return [{"case_id": r.case_id, "source": r.source, "url": r.url} for r in rows[:20]]
