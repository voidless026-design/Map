"""MySQL engine construction (optional, free backend).

Requires a MySQL/MariaDB server and a driver (e.g. PyMySQL). Install with:
    pip install pymysql
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from openatlas.config import Config


def make_url() -> str:
    if Config.database.url:
        return Config.database.url
    c = Config.database
    port = c.port or "3306"
    return f"mysql+pymysql://{c.user}:{c.password}@{c.host}:{port}/{c.name}"


def make_engine() -> Engine:
    return create_engine(make_url(), echo=Config.database.echo, future=True, pool_pre_ping=True)
