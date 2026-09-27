"""Search the brain like a search engine: parse the query, weigh titles, gate on relevance.

Why the old version drifted off-topic: when "all words" found too few passages it fell back
to "any word", so one common word ("history", "world") matched anything; stopwords counted
as terms; titles carried no weight; and it always returned k results, however weak.

Now:
1. **Parse** - ``"exact phrase"``, ``-exclude``, English stopwords dropped (kept only when the
   query is nothing but stopwords).
2. **Candidates** - title/alias hits (exact, then all-terms, then most-terms), passages with
   all terms, and - for longer queries - passages with at least 60% of the terms. Never
   "any single word".
3. **Score per article** - BM25 of the best passage (+ a little for a second one), title
   strength (exact title/alias > every term in the title > some), term coverage, phrase and
   proximity bonuses, and vector similarity when embeddings exist.
4. **Gate** - articles covering under half the terms, or scoring under 35% of the best, are
   dropped. Fewer, on-topic results beat k weak ones. Every hit says *why* it matched.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from openatlas.kb import embed, store

_WORD = re.compile(r"\w+", re.UNICODE)
_TOKEN = re.compile(r'(-?)"([^"]+)"|(-?)(\w+)', re.UNICODE)

STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had
has have having he her here hers herself him himself his how i if in into is it its itself just
me more most my myself no nor not now of off on once only or other our ours ourselves out over own
same she should so some such than that the their theirs them themselves then there these they
this those through to too under until up very was we were what when where which while who whom
why will with would you your yours yourself yourselves tell explain describe know about what's
""".split())

GATE_COVERAGE = 0.5      # an article must contain at least half the query terms ...
GATE_RELATIVE = 0.35     # ... and score at least 35% of the best article
MIN_SHOULD_MATCH = 0.6   # relaxed candidate pass for longer queries


@dataclass
class Query:
    raw: str
    terms: List[str] = field(default_factory=list)       # meaningful words, in order
    phrases: List[str] = field(default_factory=list)     # "exact phrases"
    exclude: List[str] = field(default_factory=list)     # -words / -"phrases"

    @property
    def norm(self) -> str:
        return store.norm_title(self.raw.replace('"', " ").replace("-", " ")) if not self.exclude \
            else " ".join(self.terms)


def parse(q: str) -> Query:
    """Split a query into terms, phrases and exclusions (search-engine syntax)."""
    out = Query(raw=q.strip())
    words: List[str] = []
    for neg_p, phrase, neg_w, word in _TOKEN.findall(q):
        if phrase:
            toks = [t.lower() for t in _WORD.findall(phrase)]
            (out.exclude if neg_p else out.phrases).append(" ".join(toks))
            if not neg_p:
                words.extend(toks)
        elif word:
            (out.exclude if neg_w else words).append(word.lower())
    meaningful = [w for w in words if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
    out.terms = list(dict.fromkeys(meaningful or [w for w in words if len(w) > 1]))[:12]
    return out


def _stem(w: str) -> str:
    """Tiny suffix stripper for coverage checks (the index itself uses Porter stemming)."""
    for suf in ("ations", "ation", "ingly", "ings", "ing", "edly", "ies", "ied", "es", "ed",
                "ly", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _present(terms: List[str], text: str) -> Set[str]:
    low = text.lower()
    return {t for t in terms if re.search(r"\b" + re.escape(_stem(t)), low)}


def _fts(terms: List[str], joiner: str = " ") -> str:
    return joiner.join(f'"{t}"' for t in terms)


def _snippet(text: str, terms: List[str], width: int = 220) -> str:
    low = text.lower()
    pos = min((low.find(_stem(t)) for t in terms if low.find(_stem(t)) >= 0), default=0)
    a = max(0, pos - width // 3)
    return ("…" if a else "") + text[a:a + width].strip() + ("…" if a + width < len(text) else "")


def _chunk_candidates(con: Any, fq: str, tag: Optional[str], limit: int) -> List[Any]:
    sql = ("SELECT f.rowid cid, bm25(chunks_fts) score, c.text, c.doc_id FROM chunks_fts f "
           "JOIN chunks c ON c.id=f.rowid ")
    args: List[Any] = []
    if tag:
        sql += "JOIN doc_tags t ON t.doc_id=c.doc_id AND t.tag=? "
        args.append(tag)
    sql += "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?"
    return con.execute(sql, args + [fq, limit]).fetchall()


def search(query: str, k: int = 8, *, tag: Optional[str] = None, use_vectors: bool = True,
           gate: bool = True) -> List[Dict[str, Any]]:
    """Top-k on-topic articles for ``query``: title, url, licence, snippet, score and why."""
    q = parse(query)
    if not q.terms:
        return []
    n = len(q.terms)
    docs: Dict[int, Dict[str, Any]] = {}

    def doc(doc_id: int) -> Dict[str, Any]:
        return docs.setdefault(doc_id, {"chunks": [], "title_score": 0.0, "title_why": "",
                                        "title_text": ""})

    with store.connect() as con:
        # 1) titles and aliases: exact first, then every term, then most terms
        # exact: the whole query, or the query minus question words ("what is X" -> "X")
        for norm in dict.fromkeys((q.norm, " ".join(q.terms))):
            for r in con.execute("SELECT doc_id, title, kind FROM titles WHERE norm=?", (norm,)):
                d = doc(r["doc_id"])
                d["title_score"], d["title_why"], d["title_text"] = 1.0, "exact " + r["kind"], r["title"]
        for fq, strength in ((_fts(q.terms), 0.75), (_fts(q.terms, " OR "), 0.0)):
            for r in con.execute("SELECT t.doc_id, t.title, t.kind FROM titles_fts f JOIN titles t "
                                 "ON t.id=f.rowid WHERE titles_fts MATCH ? ORDER BY bm25(titles_fts) "
                                 "LIMIT 60", (fq,)):
                share = len(_present(q.terms, r["title"])) / n
                s = strength or (0.5 * share if share >= GATE_COVERAGE else 0.0)
                # a short title that is (almost) only the query beats a long one that contains it
                extra = len(_WORD.findall(r["title"])) - n
                s *= 1.0 if extra <= 0 else max(0.6, 1 - 0.08 * extra)
                d = docs.get(r["doc_id"])
                if s and (d is None or s > d["title_score"]):
                    d = doc(r["doc_id"])
                    d["title_score"], d["title_text"] = s, r["title"]
                    d["title_why"] = ("title" if r["kind"] == "title" else "alias") + \
                        (" has all words" if strength else f" has {round(share * n)}/{n} words")
        # 2) passages: all terms (+ phrases), then the relaxed most-terms pass
        passes = [_fts(q.terms) + "".join(f' "{p}"' for p in q.phrases)]
        if n >= 3:
            passes.append(_fts(q.terms, " OR "))
        need = math.ceil(MIN_SHOULD_MATCH * n)
        for i, fq in enumerate(passes):
            for r in _chunk_candidates(con, fq, tag, 200 if i == 0 else 400):
                if i and len(_present(q.terms, r["text"])) < need:
                    continue
                doc(r["doc_id"])["chunks"].append(r)
        if not docs:
            return []
        ids = list(docs)
        marks = ",".join("?" * len(ids))
        meta = {r["id"]: r for r in con.execute(
            f"SELECT id, title, url, license, source, key FROM documents WHERE id IN ({marks})", ids)}
        if tag:  # title hits must respect the tag filter too
            tagged = {r["doc_id"] for r in con.execute(
                f"SELECT doc_id FROM doc_tags WHERE tag=? AND doc_id IN ({marks})", [tag] + ids)}
            docs = {i: d for i, d in docs.items() if i in tagged}
        for doc_id, d in docs.items():  # title-only hits still need a passage to show
            if not d["chunks"]:
                r = con.execute("SELECT id cid, 0.0 score, text, doc_id FROM chunks WHERE doc_id=? "
                                "ORDER BY ord LIMIT 1", (doc_id,)).fetchone()
                if r:
                    d["chunks"].append(r)
        vecs: Dict[int, Any] = {}
        if use_vectors:
            cids = [c["cid"] for d in docs.values() for c in d["chunks"][:1]]
            if cids:
                vecs = {r["chunk_id"]: r["vec"] for r in con.execute(
                    f"SELECT chunk_id, vec FROM vectors WHERE chunk_id IN ({','.join('?' * len(cids))})",
                    cids)}

    best_bm25 = min((c["score"] for d in docs.values() for c in d["chunks"]), default=0.0) or -1.0
    qvec = embed.embed_texts([query])[0] if vecs else None
    scored = []
    for doc_id, d in docs.items():
        m = meta.get(doc_id)
        if m is None or not d["chunks"]:
            continue
        chunks = sorted(d["chunks"], key=lambda c: c["score"])
        top = chunks[0]
        text_all = (m["title"] + " " + top["text"]).lower()
        if any(re.search(r"\b" + re.escape(x), text_all) for x in q.exclude):
            continue
        found = _present(q.terms, " ".join((m["title"], d.get("title_text", ""), top["text"])))
        coverage = len(found) / n
        bm = top["score"] / best_bm25 if best_bm25 else 0.0
        if len(chunks) > 1:
            bm += 0.15 * chunks[1]["score"] / best_bm25
        phrase = any(p in text_all for p in q.phrases) or (n > 1 and " ".join(q.terms) in text_all)
        s = 0.40 * min(bm, 1.15) + 0.40 * d["title_score"] + 0.20 * coverage + (0.10 if phrase else 0)
        if qvec is not None and top["cid"] in vecs:
            s += 0.15 * max(0.0, embed.cosine(qvec, embed.unpack(vecs[top["cid"]])))
        why = [w for w in (d["title_why"], f"{len(found)}/{n} words", "phrase" if phrase else "") if w]
        scored.append((s, coverage, d["title_score"], m, top, why))

    scored.sort(key=lambda x: -x[0])
    if not scored:
        return []
    top_score = scored[0][0]
    out = []
    for s, coverage, title_score, m, top, why in scored:
        if gate and n >= 2 and coverage < GATE_COVERAGE and title_score < 0.9:
            continue
        if gate and s < GATE_RELATIVE * top_score:
            continue
        out.append({"title": m["title"], "url": m["url"], "license": m["license"],
                    "source": m["source"], "key": m["key"], "chunk_id": top["cid"],
                    "snippet": _snippet(top["text"], q.terms), "text": top["text"],
                    "score": round(s, 3), "why": ", ".join(why)})
        if len(out) >= k:
            break
    return out
