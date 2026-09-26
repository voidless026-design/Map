"""SQLite engine construction (the default, zero-config backend)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine

from openatlas.config import Config


def make_url() -> str:
    path = Path(Config.database.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine() -> Engine:
    return create_engine(make_url(), echo=Config.database.echo, future=True)
