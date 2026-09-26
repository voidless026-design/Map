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


def reset_for_tests(url: str = "sqlite:///:memory:") -> None:  # pragma: no cover
    """Point the layer at an in-memory DB (used by the test-suite)."""
    global _ENGINE, _SESSIONMAKER
    from sqlalchemy import create_engine

    _ENGINE = create_engine(url, future=True)
    _SESSIONMAKER = sessionmaker(bind=_ENGINE, future=True)
    Base.metadata.create_all(_ENGINE)
