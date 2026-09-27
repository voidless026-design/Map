"""The brain's storage: one SQLite file with FTS5 full-text search.

Designed for a spinning external HDD and a busy desktop: WAL journaling, a small page
cache (~16 MB), short transactions, and no memory-mapped I/O. Everything the AI "knows"
is here, with attribution: Wikipedia text keeps its URL, revision and CC BY-SA licence;
investigation findings keep their case id and source links.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from openatlas.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,          -- e.g. wikipedia:Group_theory, case:ab12cd34ef56
  source TEXT NOT NULL,              -- wikipedia | case | manifest
  title TEXT NOT NULL,
  url TEXT,
  revid INTEGER,
  license TEXT,
  fetched_at TEXT,
  chars INTEGER DEFAULT 0,
  hash TEXT
);
CREATE TABLE IF NOT EXISTS doc_tags (
  doc_id INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (doc_id, tag)
);
CREATE INDEX IF NOT EXISTS doc_tags_tag ON doc_tags(tag);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL,
  ord INTEGER NOT NULL,
  text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
-- contentless: the index doesn't store the text a second time (half the disk at depth 2)
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text, content='', tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS vectors (
  chunk_id INTEGER PRIMARY KEY, model TEXT, dim INTEGER, vec BLOB
);
CREATE TABLE IF NOT EXISTS queue (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE NOT NULL,          -- kind:title
  kind TEXT NOT NULL,                -- article | category | vital-list
  title TEXT NOT NULL,
  tier INTEGER NOT NULL,
  depth INTEGER DEFAULT 0,
  seed TEXT,
  tags TEXT DEFAULT '[]',
  priority INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',     -- pending | done | skipped | failed
  attempts INTEGER DEFAULT 0,
  note TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS queue_next ON queue(status, priority DESC, tier, id);
CREATE INDEX IF NOT EXISTS queue_seed ON queue(seed);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

_LOCK = threading.RLock()
_INIT: set = set()


#: Per-thread/task database override, used by the doctor's self-test so it can exercise the
#: real store + search code on a throwaway brain without touching yours (or any global).
_OVERRIDE: ContextVar[Optional[Path]] = ContextVar("openatlas_brain_override", default=None)


@contextmanager
def use_path(path: Path) -> Iterator[Path]:
    """Point this thread/task at another brain file for the duration of the block."""
    token = _OVERRIDE.set(Path(path))
    try:
        yield Path(path)
    finally:
        _OVERRIDE.reset(token)


def db_path() -> Path:
    override = _OVERRIDE.get()
    if override is not None:
        override.parent.mkdir(parents=True, exist_ok=True)
        return override
    d = Path(Config.files.brain_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / "brain.sqlite"


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A short-lived connection (safe across threads; serialised writes)."""
    path = db_path()
    with _LOCK:
        con = sqlite3.connect(path, timeout=30)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA cache_size=-16000")  # ~16 MB page cache
            con.execute("PRAGMA mmap_size=0")
            if str(path) not in _INIT:
                con.executescript(SCHEMA)
                _INIT.add(str(path))
            yield con
            con.commit()
        finally:
            con.close()


def reset_init_cache() -> None:  # tests switch data dirs
    _INIT.clear()


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
_SKIP_SECTIONS = re.compile(r"^==+\s*(References|External links|See also|Further reading|Notes|"
                            r"Bibliography|Sources|Citations|Footnotes)\s*==+\s*$", re.I | re.M)


def clean_article(text: str) -> str:
    """Cut reference/link sections and turn '== Heading ==' into plain lines."""
    m = _SKIP_SECTIONS.search(text)
    if m:
        text = text[: m.start()]
    text = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk(text: str, size: int = 1200) -> List[str]:
    """Split on paragraph boundaries into ~size-char chunks."""
    out, cur = [], ""
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        if len(cur) + len(para) + 1 > size and cur:
            out.append(cur)
            cur = ""
        while len(para) > size * 1.5:  # very long paragraph: hard split on sentence
            cut = para.rfind(". ", 0, size) + 1 or size
            out.append((cur + " " + para[:cut]).strip())
            cur, para = "", para[cut:].strip()
        cur = (cur + "\n" + para).strip()
    if cur:
        out.append(cur)
    return out


def upsert_document(*, key: str, source: str, title: str, text: str, url: str = "",
                    revid: Optional[int] = None, license: str = "", tags: Iterable[str] = ()) -> int:
    """Insert or replace a document and its chunks. Returns the document id."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    with connect() as con:
        row = con.execute("SELECT id, hash FROM documents WHERE key=?", (key,)).fetchone()
        if row and row["hash"] == digest:
            doc_id = row["id"]
        else:
            if row:
                doc_id = row["id"]
                _delete_chunks(con, doc_id)
                con.execute("UPDATE documents SET title=?, url=?, revid=?, license=?, fetched_at=?, "
                            "chars=?, hash=? WHERE id=?",
                            (title, url, revid, license, now(), len(text), digest, doc_id))
            else:
                cur = con.execute(
                    "INSERT INTO documents(key, source, title, url, revid, license, fetched_at, chars, hash)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (key, source, title, url, revid, license, now(), len(text), digest))
                doc_id = int(cur.lastrowid)
            for i, piece in enumerate(chunk(text)):
                cid = con.execute("INSERT INTO chunks(doc_id, ord, text) VALUES (?,?,?)",
                                  (doc_id, i, piece)).lastrowid
                con.execute("INSERT INTO chunks_fts(rowid, text) VALUES (?,?)", (cid, piece))
        for tag in tags:
            con.execute("INSERT OR IGNORE INTO doc_tags(doc_id, tag) VALUES (?,?)", (doc_id, tag))
        return int(doc_id)


def _delete_chunks(con: sqlite3.Connection, doc_id: int) -> None:
    for r in con.execute("SELECT id, text FROM chunks WHERE doc_id=?", (doc_id,)).fetchall():
        # contentless FTS5: deletes must repeat the indexed values
        con.execute("INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', ?, ?)",
                    (r["id"], r["text"]))
        con.execute("DELETE FROM vectors WHERE chunk_id=?", (r["id"],))
    con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))


def get_document(key: str) -> Optional[Dict[str, Any]]:
    with connect() as con:
        row = con.execute("SELECT * FROM documents WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = [r["tag"] for r in con.execute("SELECT tag FROM doc_tags WHERE doc_id=?", (row["id"],))]
        d["chunks"] = con.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (row["id"],)).fetchone()[0]
        return d


def add_case(report: Dict[str, Any]) -> int:
    """Store an investigation's findings so later cases and questions can find them."""
    t = report.get("target", {})
    lines = [f"Investigation {report.get('case_id')} of {t.get('type')} '{t.get('value')}' "
             f"({report.get('finished_at')}). Purpose: {report.get('purpose')}."]
    for e in report.get("evidence", []):
        lines.append(f"[{e.get('status')}] {e.get('title')} — {e.get('snippet', '')[:300]} "
                     f"(source: {e.get('source')}; {e.get('url') or 'no link'})")
    return upsert_document(key=f"case:{report.get('case_id')}", source="case",
                           title=f"Case: {t.get('value')}", text="\n".join(lines),
                           url="", license="private (your own investigation)",
                           tags=["case", f"target-type:{t.get('type')}"])


# --------------------------------------------------------------------------- #
# meta / stats
# --------------------------------------------------------------------------- #
def set_meta(key: str, value: Any) -> None:
    with connect() as con:
        con.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))


def get_meta(key: str, default: Any = None) -> Any:
    with connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default


def stats() -> Dict[str, Any]:
    with connect() as con:
        docs = con.execute("SELECT source, COUNT(*) n, COALESCE(SUM(chars),0) c FROM documents GROUP BY source").fetchall()
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vecs = con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        q = con.execute("SELECT tier, status, COUNT(*) n FROM queue GROUP BY tier, status").fetchall()
    tiers: Dict[int, Dict[str, int]] = {}
    for r in q:
        tiers.setdefault(r["tier"], {})[r["status"]] = r["n"]
    path = db_path()
    size = sum(p.stat().st_size for p in path.parent.glob(path.name + "*") if p.exists())
    return {
        "path": str(path), "bytes": size,
        "documents": {r["source"]: r["n"] for r in docs},
        "chars": sum(r["c"] for r in docs), "chunks": chunks, "vectors": vecs,
        "queue": {str(k): v for k, v in sorted(tiers.items())},
    }
