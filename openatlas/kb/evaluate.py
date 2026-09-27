"""Measure whether brain search stays on-topic - so nobody has to eyeball answers.

Two query sets:

* the **fixture corpus** (`FIXTURE_DOCS` + `FIXTURE_QUERIES`): look-alike distractors on
  purpose ("Roman Empire" vs "Holy Roman Empire" vs "Empire (film)"), used by the doctor and
  the tests so a ranking regression is caught before it reaches you;
* **your brain**: queries generated from what is actually stored (each article's title and
  aliases must find that article first) plus an optional golden file of your own questions
  (``data/eval/search_golden.jsonl``: ``{"q": ..., "expect": [...], "ok": [...]}``).

Metrics: P@1 (right answer first), MRR@5, nDCG@5, and the **off-topic rate** - the share of
returned results that are neither the answer nor an acceptable related article. Queries with
``expect: []`` must return nothing at all.
"""

from __future__ import annotations

import json
import math
import random
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openatlas.config import Config

Search = Callable[..., List[Dict[str, Any]]]

THRESHOLDS = {"p_at_1": 0.85, "mrr": 0.85, "ndcg": 0.8, "off_topic": 0.15}

_P = "\n\n"
FIXTURE_DOCS: List[Dict[str, Any]] = [
    {"title": "Roman Empire", "aliases": ["Imperium Romanum"], "text": _P.join([
        "The Roman Empire was the post-Republican state of ancient Rome, ruled by emperors from "
        "Augustus in 27 BC. At its height it controlled the Mediterranean, much of Europe, the "
        "Near East and North Africa.",
        "The fall of the Western Roman Empire in 476 AD, when Odoacer deposed Romulus Augustulus, "
        "is traditionally taken as the end of antiquity. The eastern half survived as the "
        "Byzantine Empire."])},
    {"title": "Holy Roman Empire", "aliases": [], "text": _P.join([
        "The Holy Roman Empire was a political entity in Central Europe from 800 or 962 until "
        "1806, ruled by an elected emperor. Its heartland was the German kingdoms.",
        "The Holy Roman Emperor was chosen by prince-electors and crowned by the pope; Voltaire "
        "joked it was neither holy, nor Roman, nor an empire."])},
    {"title": "Empire (film)", "aliases": [], "text":
        "Empire is a 1964 silent film by Andy Warhol showing eight hours of slow-motion footage "
        "of the Empire State Building. It has no plot, no dialogue and no story."},
    {"title": "History of Rome", "aliases": [], "text": _P.join([
        "The history of Rome covers the city from its founding, traditionally in 753 BC, through "
        "the kingdom, the republic, the empire and the papacy to the modern capital of Italy.",
        "Rome was sacked by the Visigoths in 410 and by the Vandals in 455."])},
    {"title": "Python (programming language)", "aliases": ["Python language", "CPython"], "text":
        "Python is a high-level programming language created by Guido van Rossum and first "
        "released in 1991. Its design emphasises code readability and significant indentation. "
        "Python is dynamically typed and garbage-collected, and supports multiple paradigms."},
    {"title": "Pythonidae", "aliases": ["Python (snake)", "Pythons"], "text":
        "The Pythonidae, commonly known as pythons, are a family of nonvenomous snakes found in "
        "Africa, Asia and Australia. Pythons kill their prey by constriction; the reticulated "
        "python is among the longest snakes in the world."},
    {"title": "Photosynthesis", "aliases": [], "text":
        "Photosynthesis is the process by which plants, algae and some bacteria convert light "
        "energy from sunlight into chemical energy stored in glucose, releasing oxygen from "
        "water. It takes place in the chloroplasts of plant cells."},
    {"title": "Cellular respiration", "aliases": [], "text":
        "Cellular respiration is the process by which cells break down glucose with oxygen to "
        "release energy as ATP, producing carbon dioxide and water. It occurs in the mitochondria "
        "of plant and animal cells alike."},
    {"title": "Black hole", "aliases": [], "text":
        "A black hole is a region of spacetime where gravity is so strong that nothing, not even "
        "light, can escape. The boundary of no escape is called the event horizon. Stellar black "
        "holes form when massive stars collapse."},
    {"title": "Black Death", "aliases": ["Bubonic plague pandemic", "The Plague"], "text":
        "The Black Death was a bubonic plague pandemic that struck Europe and Asia from 1346 to "
        "1353, killing perhaps half of Europe's population in the medieval period. It was caused "
        "by the bacterium Yersinia pestis, spread by fleas on rats."},
    {"title": "Machine learning", "aliases": ["ML"], "text":
        "Machine learning is a field of artificial intelligence in which statistical algorithms "
        "learn from data and generalise to unseen data. Deep learning uses neural networks with "
        "many layers; applications include image recognition and translation."},
    {"title": "Learning", "aliases": [], "text":
        "Learning is the process of acquiring new understanding, knowledge, behaviours or skills. "
        "Humans, animals and some machines learn; education and practice support learning."},
    {"title": "World War II", "aliases": ["Second World War", "WWII", "WW2"], "text":
        "World War II was a global conflict from 1939 to 1945 between the Allies and the Axis "
        "powers. It began with the German invasion of Poland and ended with the surrender of "
        "Germany in May and Japan in September 1945."},
    {"title": "FIFA World Cup", "aliases": ["World Cup"], "text":
        "The FIFA World Cup is an international association football competition held every four "
        "years between men's national teams. The first tournament was held in 1930 in Uruguay."},
]

FIXTURE_QUERIES: List[Dict[str, Any]] = [
    {"q": "roman empire", "expect": ["Roman Empire"], "ok": ["Holy Roman Empire", "History of Rome"]},
    {"q": "fall of the western roman empire", "expect": ["Roman Empire"], "ok": ["History of Rome"]},
    {"q": "holy roman emperor elected", "expect": ["Holy Roman Empire"], "ok": []},
    {"q": "python programming language", "expect": ["Python (programming language)"], "ok": []},
    {"q": "python snake constriction", "expect": ["Pythonidae"], "ok": []},
    {"q": "how do plants turn sunlight into energy", "expect": ["Photosynthesis"],
     "ok": ["Cellular respiration"]},
    {"q": "black hole event horizon", "expect": ["Black hole"], "ok": []},
    {"q": "machine learning neural networks", "expect": ["Machine learning"], "ok": ["Learning"]},
    {"q": "second world war", "expect": ["World War II"], "ok": []},
    {"q": "WWII", "expect": ["World War II"], "ok": []},
    {"q": "the plague in medieval europe", "expect": ["Black Death"], "ok": []},
    {"q": '"event horizon"', "expect": ["Black hole"], "ok": []},
    {"q": "empire -film -holy", "expect": ["Roman Empire"], "ok": ["History of Rome"]},
    {"q": "quantum chromodynamics gluon", "expect": [], "ok": []},  # not in the brain: say so
]


def load_fixture_corpus() -> None:
    """Write the fixture corpus into the *current* brain (use inside ``store.use_path``)."""
    from openatlas.kb import store

    for d in FIXTURE_DOCS:
        key = "fixture:" + d["title"]
        store.upsert_document(key=key, source="wikipedia", title=d["title"], text=d["text"],
                              url="https://example.org/" + d["title"].replace(" ", "_"),
                              license="CC BY-SA 4.0")
        store.add_aliases(key, d["aliases"])


def score(queries: List[Dict[str, Any]], search: Search, k: int = 5) -> Dict[str, Any]:
    """Run ``queries`` through ``search`` and compute the metrics (binary relevance)."""
    p1 = rr = ndcg = 0.0
    returned = off = 0
    answerable = 0
    failures: List[Dict[str, Any]] = []
    for item in queries:
        hits = [h["title"] for h in search(item["q"], k=k)][:k]
        expect, ok = set(item.get("expect", [])), set(item.get("ok", []))
        returned += len(hits)
        stray = [h for h in hits if h not in expect and h not in ok]
        off += len(stray)
        if not expect:  # the right answer is "nothing in the brain"
            if hits:
                failures.append({"q": item["q"], "wanted": "no results", "got": hits})
            continue
        answerable += 1
        rank = next((i for i, h in enumerate(hits) if h in expect), None)
        if rank == 0:
            p1 += 1
        if rank is not None:
            rr += 1 / (rank + 1)
        dcg = sum(1 / math.log2(i + 2) for i, h in enumerate(hits) if h in expect)
        ideal = sum(1 / math.log2(i + 2) for i in range(min(len(expect), k)))
        ndcg += dcg / ideal if ideal else 0.0
        if rank != 0 or stray:
            failures.append({"q": item["q"], "wanted": sorted(expect), "got": hits,
                             "off_topic": stray})
    n = max(answerable, 1)
    metrics = {"p_at_1": round(p1 / n, 3), "mrr": round(rr / n, 3), "ndcg": round(ndcg / n, 3),
               "off_topic": round(off / returned, 3) if returned else 0.0}
    passed = (metrics["p_at_1"] >= THRESHOLDS["p_at_1"] and metrics["mrr"] >= THRESHOLDS["mrr"]
              and metrics["ndcg"] >= THRESHOLDS["ndcg"]
              and metrics["off_topic"] <= THRESHOLDS["off_topic"]
              and not any(f.get("wanted") == "no results" for f in failures))
    return {"ok": passed, "queries": len(queries), "metrics": metrics,
            "thresholds": THRESHOLDS, "failures": failures}


def eval_fixture(search: Optional[Search] = None) -> Dict[str, Any]:
    """Score ``search`` (default: the real one) on the distractor corpus, in a throwaway brain."""
    from openatlas.kb import retrieve, store

    search = search or (lambda q, k=5: retrieve.search(q, k=k, use_vectors=False))
    with tempfile.TemporaryDirectory() as d, store.use_path(Path(d) / "brain.sqlite"):
        load_fixture_corpus()
        return score(FIXTURE_QUERIES, search)


def brain_queries(sample: int = 200, seed: int = 7) -> List[Dict[str, Any]]:
    """Known-item queries from your own brain: each title (and alias) must find its article."""
    from openatlas.kb import store

    with store.connect() as con:
        rows = con.execute("SELECT d.id, d.title FROM documents d WHERE d.source != 'case'").fetchall()
        rng = random.Random(seed)
        picked = rng.sample(rows, min(sample, len(rows)))
        out = []
        for r in picked:
            out.append({"q": r["title"], "expect": [r["title"]], "ok": []})
            alias = con.execute("SELECT title FROM titles WHERE doc_id=? AND kind='alias' LIMIT 1",
                                (r["id"],)).fetchone()
            if alias:
                out.append({"q": alias["title"], "expect": [r["title"]], "ok": []})
    golden = Path(Config.files.project_root) / "data" / "eval" / "search_golden.jsonl"
    if golden.exists():
        for line in golden.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def eval_brain(sample: int = 200) -> Dict[str, Any]:
    """Score the real search on queries generated from your brain (+ your golden file).

    Known-item queries are lenient about *what else* is returned (other articles may share a
    title word); only the right article being first counts, so the off-topic rate is not used."""
    from openatlas.kb import retrieve

    queries = brain_queries(sample)
    if not queries:
        return {"ok": True, "queries": 0, "metrics": {}, "failures": [],
                "note": "brain is empty - nothing to evaluate yet"}
    known = [dict(q, ok=["*"]) for q in queries]
    result = score(known, lambda q, k=5: retrieve.search(q, k=k, use_vectors=False))
    m = result["metrics"]
    result["ok"] = m["p_at_1"] >= THRESHOLDS["p_at_1"] and m["mrr"] >= THRESHOLDS["mrr"]
    m.pop("off_topic", None)
    return result


def legacy_or_search(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """The pre-rework ranker (all words, else ANY word; no titles; always k results).

    Kept only as the doctor's known-bad fixture: the evaluator must fail it, which proves the
    evaluator can still detect an off-topic regression."""
    import re

    from openatlas.kb import store

    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:12]
    if not words:
        return []
    rows: List[Any] = []
    with store.connect() as con:
        for joiner in (" ", " OR "):
            rows = con.execute(
                "SELECT c.doc_id, d.title, bm25(chunks_fts) s FROM chunks_fts f JOIN chunks c "
                "ON c.id=f.rowid JOIN documents d ON d.id=c.doc_id WHERE chunks_fts MATCH ? "
                "ORDER BY s LIMIT 100", (joiner.join(f'"{w}"' for w in words),)).fetchall()
            if len(rows) >= k:
                break
    out, seen = [], set()
    for r in rows:
        if r["doc_id"] not in seen:
            seen.add(r["doc_id"])
            out.append({"title": r["title"]})
    return out[:k]
