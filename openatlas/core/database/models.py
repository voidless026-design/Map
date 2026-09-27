"""SQLAlchemy models for OpenAtlas investigation storage.

Every function run and its output is logged (OAtlas parity), so reports and history
can be reconstructed. Backends: SQLite (default), MySQL, PostgreSQL - all free.
"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


class Session(Base):
    """An investigation session groups related function runs."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utcnow)


class FunctionRun(Base):
    """A single function execution and its (JSON) output."""

    __tablename__ = "function_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    function_name: Mapped[str] = mapped_column(String(128), index=True)
    engine_name: Mapped[str] = mapped_column(String(128), default="")
    arguments_json: Mapped[str] = mapped_column(Text, default="{}")
    function_output: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utcnow)


class Case(Base):
    """An investigation (v2 pipeline): target, purpose, status and a JSON report."""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    purpose: Mapped[str] = mapped_column(String(500), default="")
    target: Mapped[str] = mapped_column(String(500), default="")
    target_type: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="running")
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[_dt.datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[_dt.datetime | None] = mapped_column(DateTime, nullable=True)


class CaseEvidence(Base):
    """One piece of evidence in a case (denormalised for cross-case lookups)."""

    __tablename__ = "case_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    evidence_id: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="")
    entity_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    entity_value: Mapped[str] = mapped_column(String(500), default="", index=True)
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="unverified")
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
