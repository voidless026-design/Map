"""Search the brain: BM25 full-text candidates, optionally re-ranked by vectors (RRF)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from openatlas.kb import embed, store

_WORD = re.compile(r"\w+", re.UNICODE)


def _fts_query(q: str, mode: str) -> Optional[str]:
    words = [w for w in _WORD.findall(q.lower()) if len(w) > 1][:12]
    if not words:
        return None
    joiner = " " if mode == "and" else " OR "
    return joiner.join(f'"{w}"' for w in words)


def _snippet(text: str, query: str, width: int = 220) -> str:
    low = text.lower()
    pos = min((low.find(w) for w in _WORD.findall(query.lower()) if low.find(w) >= 0), default=0)
    a = max(0, pos - width // 3)
    return ("…" if a else "") + text[a:a + width].strip() + ("…" if a + width < len(text) else "")


def search(query: str, k: int = 8, *, tag: Optional[str] = None,
           use_vectors: bool = True) -> List[Dict[str, Any]]:
    """Top-k chunks for ``query`` with title, url, licence and a snippet."""
    rows: List[Any] = []
    with store.connect() as con:
        for mode in ("and", "or"):
            fq = _fts_query(query, mode)
            if not fq:
                return []
            sql = ("SELECT f.rowid cid, bm25(chunks_fts) score, c.text, c.doc_id, d.title, d.url, "
                   "d.license, d.source, d.key FROM chunks_fts f JOIN chunks c ON c.id=f.rowid "
                   "JOIN documents d ON d.id=c.doc_id ")
            args: List[Any] = [fq]
            if tag:
                sql += "JOIN doc_tags t ON t.doc_id=d.id AND t.tag=? "
                args.insert(0, tag)
            sql += "WHERE chunks_fts MATCH ? ORDER BY score LIMIT 100"
            rows = con.execute(sql, args).fetchall()
            if len(rows) >= k:
                break
        vec_rows = {}
        if use_vectors and rows:
            ids = [r["cid"] for r in rows]
            q = ",".join("?" * len(ids))
            vec_rows = {r["chunk_id"]: r["vec"] for r in
                        con.execute(f"SELECT chunk_id, vec FROM vectors WHERE chunk_id IN ({q})", ids)}
    ranked = list(rows)
    if vec_rows:
        qv = embed.embed_texts([query])
        if qv:
            sims = {cid: embed.cosine(qv[0], embed.unpack(b)) for cid, b in vec_rows.items()}
            by_vec = sorted(sims, key=lambda c: -sims[c])
            vrank = {cid: i for i, cid in enumerate(by_vec)}
            # Reciprocal-rank fusion of the BM25 order and the vector order.
            ranked = sorted(rows, key=lambda r: -(1 / (60 + rows.index(r)) +
                                                  1 / (60 + vrank.get(r["cid"], 1000))))
    out, seen_docs = [], set()
    for r in ranked:
        if r["doc_id"] in seen_docs:  # one best chunk per document
            continue
        seen_docs.add(r["doc_id"])
        out.append({"title": r["title"], "url": r["url"], "license": r["license"],
                    "source": r["source"], "key": r["key"], "chunk_id": r["cid"],
                    "snippet": _snippet(r["text"], query), "text": r["text"]})
        if len(out) >= k:
            break
    return out
