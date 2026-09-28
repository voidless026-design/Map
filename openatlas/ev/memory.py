"""Context continuity: conversations, a rolling summary, and things E.V remembers about you.

Everything is local and inspectable: ``facts`` are plain sentences you can list, edit or
delete ("forget that"), and each has the line it came from.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openatlas.ev import db

KEEP_TURNS = 12  # recent messages sent verbatim; older ones live in the summary


def new_conversation(title: str = "New chat") -> int:
    with db.connect() as con:
        cur = con.execute("INSERT INTO conversations(title, created, updated) VALUES (?,?,?)",
                          (title[:80], db.now(), db.now()))
        return int(cur.lastrowid)


def conversations(limit: int = 50, q: str = "") -> List[Dict[str, Any]]:
    if q:
        return db.rows("SELECT * FROM conversations WHERE title LIKE ? ORDER BY updated DESC LIMIT ?",
                       (f"%{q}%", limit))
    return db.rows("SELECT * FROM conversations ORDER BY updated DESC LIMIT ?", (limit,))


def conversation(conv_id: int) -> Optional[Dict[str, Any]]:
    return db.one("SELECT * FROM conversations WHERE id=?", (conv_id,))


def delete_conversation(conv_id: int) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


def add(conv_id: int, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> int:
    with db.connect() as con:
        cur = con.execute("INSERT INTO messages(conv_id, role, content, meta, created) VALUES (?,?,?,?,?)",
                          (conv_id, role, content, json.dumps(meta or {}), db.now()))
        mid = int(cur.lastrowid)
        if content and role in ("user", "assistant"):
            con.execute("INSERT INTO messages_fts(rowid, content) VALUES (?, ?)", (mid, content))
        con.execute("UPDATE conversations SET updated=? WHERE id=?", (db.now(), conv_id))
        n = con.execute("SELECT COUNT(*) FROM messages WHERE conv_id=? AND role='user'", (conv_id,)).fetchone()[0]
        if role == "user" and n == 1:  # name the chat after its first question
            con.execute("UPDATE conversations SET title=? WHERE id=?", (_title(content), conv_id))
    return mid


def _title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:48] + "…") if len(t) > 48 else (t or "New chat")


def messages(conv_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    out = db.rows("SELECT * FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?", (conv_id, limit))
    for m in out:
        m["meta"] = json.loads(m["meta"] or "{}")
    return list(reversed(out))


def recent_for_model(conv_id: int) -> List[Dict[str, str]]:
    """The last few user/assistant turns, as chat messages for the model."""
    return [{"role": m["role"], "content": m["content"]} for m in messages(conv_id, KEEP_TURNS * 2)
            if m["role"] in ("user", "assistant") and m["content"]][-KEEP_TURNS:]


def set_summary(conv_id: int, summary: str) -> None:
    with db.connect() as con:
        con.execute("UPDATE conversations SET summary=? WHERE id=?", (summary[:2000], conv_id))


def refresh_summary(conv_id: int) -> str:
    """Fold turns older than the verbatim window into the conversation summary (local model when
    available; otherwise a compact extract of what was asked)."""
    msgs = [m for m in messages(conv_id, 400) if m["role"] in ("user", "assistant")]
    old = msgs[:-KEEP_TURNS]
    if not old:
        return (conversation(conv_id) or {}).get("summary", "")
    from openatlas.llm import ollama_client

    text = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in old[-40:])
    summary = ollama_client.complete(
        "Summarise this earlier part of a conversation in at most 5 short bullet points, keeping "
        "names, decisions, open tasks and preferences:\n\n" + text, max_tokens=220) if ollama_client.available() else None
    if not summary:
        asked = [m["content"][:80] for m in old if m["role"] == "user"][-6:]
        summary = "Earlier you asked about: " + "; ".join(asked)
    set_summary(conv_id, summary)
    return summary


def search(query: str, limit: int = 5, exclude_conv: Optional[int] = None) -> List[Dict[str, Any]]:
    """Earlier messages (any conversation) relevant to ``query``."""
    words = [w for w in re.findall(r"[A-Za-z0-9]{3,}", query.lower())][:8]
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in words)
    got = db.rows("SELECT m.id, m.conv_id, m.role, m.content, m.created FROM messages_fts f "
                  "JOIN messages m ON m.id=f.rowid WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts) "
                  "LIMIT ?", (match, limit * 3))
    return [g for g in got if g["conv_id"] != exclude_conv][:limit]


# ------------------------------------------------------------------ facts ("remember that...")
_REMEMBER = re.compile(r"^\s*(?:please\s+)?(?:remember|note|keep in mind)\s+(?:that\s+)?(.{3,300})$", re.I)
_FORGET = re.compile(r"^\s*(?:please\s+)?forget\s+(?:that\s+|about\s+)?(.{2,200})$", re.I)


def remember(text: str, source: str = "") -> Dict[str, Any]:
    text = text.strip().rstrip(".") + "."
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO facts(text, source, created) VALUES (?,?,?)",
                    (text[:300], source[:300], db.now()))
    return db.one("SELECT * FROM facts WHERE text=?", (text[:300],)) or {}


def forget(what: str) -> List[Dict[str, Any]]:
    """Delete facts by id or by matching words. Returns what was forgotten."""
    if what.strip().isdigit():
        gone = db.rows("SELECT * FROM facts WHERE id=?", (int(what),))
    else:
        words = [w for w in re.findall(r"[a-z0-9]{3,}", what.lower())]
        gone = [f for f in facts() if words and all(w in f["text"].lower() for w in words)]
    with db.connect() as con:
        for f in gone:
            con.execute("DELETE FROM facts WHERE id=?", (f["id"],))
    return gone


def facts() -> List[Dict[str, Any]]:
    return db.rows("SELECT * FROM facts ORDER BY id")


def fact_lines() -> List[str]:
    return [f["text"] for f in facts()]


def explicit_memory_command(text: str) -> Optional[Dict[str, Any]]:
    """'remember that I prefer metric' / 'forget my address' - handled even without the model."""
    m = _REMEMBER.match(text)
    if m:
        return {"action": "remember", "fact": remember(m.group(1), source=text)}
    m = _FORGET.match(text)
    if m:
        return {"action": "forget", "forgotten": forget(m.group(1))}
    return None
