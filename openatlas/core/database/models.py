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
