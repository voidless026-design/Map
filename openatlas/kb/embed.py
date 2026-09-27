"""Optional semantic vectors for chunks, computed by the local Ollama embedding model.

Stored as float16 (half the disk of float32). Only used to re-rank full-text candidates,
so the brain works without them; they just make "ask" answers more relevant.
"""

from __future__ import annotations

import math
import struct
from typing import List, Optional, Sequence

from openatlas.kb import store


def pack(vec: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vec)}e", *vec)


def unpack(blob: bytes) -> List[float]:
    return list(struct.unpack(f"{len(blob) // 2}e", blob))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    from openatlas.llm import ollama_client

    return ollama_client.embed(texts)


def embed_pending(batch: int = 32) -> int:
    """Embed up to ``batch`` chunks that have no vector yet. Returns how many were stored."""
    from openatlas.runtime import profiles

    model = profiles.active().embed_model
    with store.connect() as con:
        rows = con.execute("SELECT c.id, c.text FROM chunks c LEFT JOIN vectors v ON v.chunk_id=c.id "
                           "WHERE v.chunk_id IS NULL LIMIT ?", (batch,)).fetchall()
    if not rows:
        return 0
    vecs = embed_texts([r["text"][:2000] for r in rows])
    if not vecs:
        return 0
    with store.connect() as con:
        for r, v in zip(rows, vecs):
            con.execute("INSERT OR REPLACE INTO vectors(chunk_id, model, dim, vec) VALUES (?,?,?,?)",
                        (r["id"], model, len(v), pack(v)))
    return len(vecs)
