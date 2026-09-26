"""PostgreSQL engine construction (optional, free backend).

Requires a PostgreSQL server and a driver (e.g. psycopg). Install with:
    pip install "psycopg[binary]"
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from openatlas.config import Config


def make_url() -> str:
    if Config.database.url:
        return Config.database.url
    c = Config.database
    port = c.port or "5432"
    return f"postgresql+psycopg://{c.user}:{c.password}@{c.host}:{port}/{c.name}"


def make_engine() -> Engine:
    return create_engine(make_url(), echo=Config.database.echo, future=True, pool_pre_ping=True)
