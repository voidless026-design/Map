"""E.V's own local store: conversations, memory, approvals, plans, routines, mood."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openatlas.config import Config
from openatlas.kb import store as kb_store

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY, title TEXT, summary TEXT DEFAULT '', created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, conv_id INTEGER, role TEXT, content TEXT, meta TEXT DEFAULT '{}',
  created TEXT);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv_id, id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY, text TEXT UNIQUE, source TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, conv_id INTEGER, tool TEXT, args TEXT, kind TEXT, risk TEXT,
  status TEXT DEFAULT 'pending', result TEXT, created TEXT, decided TEXT);
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY, conv_id INTEGER, goal TEXT, steps TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS routines (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, steps TEXT, schedule TEXT, approved INTEGER DEFAULT 0,
  last_run TEXT, log TEXT DEFAULT '[]', created TEXT);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

_LOCK = threading.RLock()
_INIT: set = set()


def ev_dir() -> Path:
    override = kb_store._OVERRIDE.get()
    base = override.parent if override is not None else Path(Config.files.brain_dir).parent
    return kb_store.ensure_dir(base / "ev")


def path() -> Path:
    return ev_dir() / "ev.sqlite"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    p = path()
    with _LOCK:
        con = sqlite3.connect(p, timeout=30)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            if str(p) not in _INIT:
                con.executescript(SCHEMA)
                _INIT.add(str(p))
            yield con
            con.commit()
        finally:
            con.close()


def now() -> str:
    return kb_store.now()


def get(key: str, default: Any = None) -> Any:
    with connect() as con:
        row = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def put(key: str, value: Any) -> None:
    with connect() as con:
        con.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "value=excluded.value", (key, json.dumps(value)))


def rows(sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> Optional[Dict[str, Any]]:
    got = rows(sql, args)
    return got[0] if got else None


def reset_init_cache() -> None:
    _INIT.clear()
