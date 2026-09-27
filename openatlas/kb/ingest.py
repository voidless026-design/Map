"""Tiered, resumable, throttled ingestion of Wikipedia into the brain.

Tiers (all automatic; the GUI shows one progress bar):
  0  the fields-of-study seeds themselves              (~1,800 articles, minutes)
  1  Wikipedia Vital Articles, level 4                 (~10,000 articles, hours)
  2  articles in each seed's own category (depth 1)    (capped per seed)
  3  articles in relevant subcategories (depth 2)      (capped per seed)

The queue lives in the brain database, so ingestion survives restarts. Topics you search
or ask about are moved to the front ("on-demand deepening"). The worker pauses itself when
disk space or RAM runs low instead of degrading the machine.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from typing import Any, Dict, List, Optional

from openatlas.config import Config
from openatlas.kb import store
from openatlas.kb.wikipedia import LICENSE, Wiki
from openatlas.logger import get_logger

log = get_logger("openatlas.kb.ingest")

MAX_PER_SEED = int(os.getenv("OPENATLAS_KB_MAX_PER_SEED", "150"))
MIN_FREE_GB = float(os.getenv("OPENATLAS_KB_MIN_FREE_GB", "20"))
MIN_CHARS = 300
TIER_NAMES = {0: "Your fields of study", 1: "Vital articles", 2: "Depth 1 (categories)",
              3: "Depth 2 (subcategories)"}
_STOP = {"of", "and", "the", "in", "for", "on", "to", "a", "an", "studies", "science", "theory"}


# --------------------------------------------------------------------------- #
# queue
# --------------------------------------------------------------------------- #
def enqueue(kind: str, title: str, tier: int, *, depth: int = 0, seed: Optional[str] = None,
            tags: Optional[List[str]] = None, priority: int = 0) -> bool:
    """Add a task; if it exists, raise its priority. Returns True if newly added."""
    key = f"{kind}:{title}"
    with store.connect() as con:
        row = con.execute("SELECT id, priority FROM queue WHERE key=?", (key,)).fetchone()
        if row:
            if priority > row["priority"]:
                con.execute("UPDATE queue SET priority=? WHERE id=?", (priority, row["id"]))
            return False
        con.execute("INSERT INTO queue(key, kind, title, tier, depth, seed, tags, priority, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (key, kind, title, tier, depth, seed, json.dumps(tags or []), priority, store.now()))
        return True


def plan(seeds: List[Dict[str, Any]], max_tier: int = 3) -> Dict[str, int]:
    """Queue every tier up to ``max_tier`` for the given taxonomy seeds."""
    added = {"articles": 0, "categories": 0, "lists": 0}
    for s in seeds:
        tags = list(s.get("namespaces", [])) + ["seed"]
        if enqueue("article", s["title"], 0, seed=s["title"], tags=tags, priority=100):
            added["articles"] += 1
        if max_tier >= 2 and enqueue("category", "Category:" + s["title"], 2, depth=1,
                                     seed=s["title"], tags=list(s.get("namespaces", [])), priority=5):
            added["categories"] += 1
    if max_tier >= 1 and enqueue("vital-list", "Level 4", 1, tags=["vital:4"], priority=50):
        added["lists"] += 1
    store.set_meta("max_tier", max_tier)
    return added


def next_task() -> Optional[Dict[str, Any]]:
    max_tier = store.get_meta("max_tier", 3)
    with store.connect() as con:
        row = con.execute("SELECT * FROM queue WHERE status='pending' AND tier<=? "
                          "ORDER BY priority DESC, tier, id LIMIT 1", (max_tier,)).fetchone()
        return dict(row) if row else None


def mark(task_id: int, status: str, note: str = "") -> None:
    with store.connect() as con:
        con.execute("UPDATE queue SET status=?, note=?, attempts=attempts+1, updated_at=? WHERE id=?",
                    (status, note[:300], store.now(), task_id))


def seed_count(seed: str) -> int:
    with store.connect() as con:
        return con.execute("SELECT COUNT(*) FROM queue WHERE seed=? AND kind='article'",
                           (seed,)).fetchone()[0]


def _tokens(s: str) -> set:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", s.lower()) if w not in _STOP and len(w) > 2}


def relevant(seed: str, category: str) -> bool:
    return bool(_tokens(seed) & _tokens(category.replace("Category:", "")))


def boost(topic: str) -> int:
    """Move pending tasks about ``topic`` to the front; queue it if unknown. Returns rows touched."""
    topic = topic.strip()
    if len(topic) < 3:
        return 0
    with store.connect() as con:
        n = con.execute("UPDATE queue SET priority=200 WHERE status='pending' AND title LIKE ?",
                        (f"%{topic}%",)).rowcount
        known = con.execute("SELECT 1 FROM documents WHERE title LIKE ? LIMIT 1", (topic,)).fetchone()
    if not n and not known:
        enqueue("article", topic[:1].upper() + topic[1:], 0, seed=topic, tags=["on-demand"], priority=200)
        n = 1
    return n


# --------------------------------------------------------------------------- #
# worker
# --------------------------------------------------------------------------- #
async def process(task: Dict[str, Any], wiki: Wiki) -> str:
    """Run one queue task. Returns its final status."""
    kind, title = task["kind"], task["title"]
    tags = json.loads(task.get("tags") or "[]") + [f"tier:{task['tier']}"]
    if kind == "article":
        art = await wiki.article(title)
        if art is None:
            mark(task["id"], "skipped", "no such article")
            return "skipped"
        if art["disambiguation"]:
            mark(task["id"], "skipped", "disambiguation page")
            return "skipped"
        text = store.clean_article(art["text"])
        if len(text) < MIN_CHARS:
            mark(task["id"], "skipped", "too short")
            return "skipped"
        store.upsert_document(key="wikipedia:" + art["title"], source="wikipedia", title=art["title"],
                              text=text, url=art["url"], revid=art["revid"], license=LICENSE, tags=tags)
        if art["title"] != title:  # asked for a redirect ("WWII") -> remember it as an alias
            store.add_aliases("wikipedia:" + art["title"], [title])
        mark(task["id"], "done", art["title"] if art["title"] != title else "")
        return "done"
    if kind == "vital-list":
        titles = await wiki.vital_articles(4)
        for t in titles:
            enqueue("article", t, 1, tags=["vital:4"], priority=50)
        mark(task["id"], "done", f"{len(titles)} vital articles queued")
        return "done"
    if kind == "category":
        seed = task.get("seed") or ""
        room = MAX_PER_SEED - seed_count(seed)
        if room <= 0:
            mark(task["id"], "skipped", "per-seed cap reached")
            return "skipped"
        members = await wiki.category_members(title, limit=min(500, room * 2))
        added = 0
        for ns, name in members:
            if ns == 0 and added < room:
                added += enqueue("article", name, task["tier"], depth=task["depth"], seed=seed,
                                 tags=json.loads(task.get("tags") or "[]"),
                                 priority=10 - task["depth"])
            elif ns == 14 and task["depth"] < 2 and relevant(seed, name):
                enqueue("category", name, 3, depth=task["depth"] + 1, seed=seed,
                        tags=json.loads(task.get("tags") or "[]"), priority=1)
        mark(task["id"], "done", f"{added} articles queued")
        return "done"
    mark(task["id"], "failed", f"unknown task kind {kind}")
    return "failed"


def resources_ok() -> Optional[str]:
    """Reason to pause, or None."""
    free_gb = shutil.disk_usage(Config.files.brain_dir if os.path.exists(Config.files.brain_dir)
                                else os.getcwd()).free / 1024**3
    if free_gb < MIN_FREE_GB:
        return f"paused: only {free_gb:.1f} GB free on the brain drive (need {MIN_FREE_GB:.0f} GB)"
    from openatlas.runtime.resources import available_ram_gb

    if 0 < available_ram_gb() < 1.5:
        return "waiting: less than 1.5 GB RAM free"
    return None


async def run(*, max_tasks: Optional[int] = None, stop: Optional[Any] = None,
              rate: Optional[float] = None, idle_exit: bool = False) -> Dict[str, int]:
    """Work through the queue. Stops after ``max_tasks``, when ``stop`` is set, or when idle
    (if ``idle_exit``). Honours the paused flag and resource limits."""
    from openatlas.net.client import Net
    from openatlas.runtime import profiles

    done = {"done": 0, "skipped": 0, "failed": 0}
    async with Net(concurrency=1, per_host=1, timeout=30) as net:
        wiki = Wiki(net, rate=rate or profiles.active().ingest_rate)
        while not (stop is not None and stop.is_set()):
            if max_tasks is not None and sum(done.values()) >= max_tasks:
                break
            if store.get_meta("paused", False):
                store.set_meta("worker", {"state": "paused", "at": store.now()})
                if idle_exit:
                    break
                await asyncio.sleep(2)
                continue
            why = resources_ok()
            if why:
                store.set_meta("worker", {"state": why, "at": store.now()})
                if idle_exit:
                    break
                await asyncio.sleep(30)
                continue
            task = next_task()
            if task is None:
                store.set_meta("worker", {"state": "idle - everything queued is ingested", "at": store.now()})
                if idle_exit:
                    break
                await asyncio.sleep(30)
                continue
            store.set_meta("worker", {"state": "working", "task": task["title"], "tier": task["tier"],
                                      "at": store.now(), "pid": os.getpid()})
            try:
                status = await process(task, wiki)
            except Exception as exc:  # one bad page must not stop the brain
                log.warning("ingest task %s failed: %s", task["key"], exc)
                mark(task["id"], "failed" if task["attempts"] >= 2 else "pending", str(exc))
                status = "failed"
            done[status] = done.get(status, 0) + 1
    return done


def progress() -> Dict[str, Any]:
    """One-glance progress for the GUI's single progress bar."""
    s = store.stats()
    total = sum(sum(v.values()) for v in s["queue"].values())
    finished = sum(v.get("done", 0) + v.get("skipped", 0) + v.get("failed", 0) for v in s["queue"].values())
    tier_rows = []
    for tier, counts in s["queue"].items():
        t_total = sum(counts.values())
        t_done = t_total - counts.get("pending", 0)
        tier_rows.append({"tier": int(tier), "name": TIER_NAMES.get(int(tier), tier),
                          "done": t_done, "total": t_total})
    current = next((r for r in tier_rows if r["done"] < r["total"]), None)
    from openatlas.runtime import profiles

    rate = max(profiles.active().ingest_rate, 0.1)  # articles per second, roughly
    remaining = total - finished
    return {
        "articles": s["documents"].get("wikipedia", 0), "cases": s["documents"].get("case", 0),
        "bytes": s["bytes"], "path": s["path"], "chunks": s["chunks"], "vectors": s["vectors"],
        "queued": total, "finished": finished, "remaining": remaining,
        "percent": round(100 * finished / total, 1) if total else 0.0,
        "tiers": tier_rows, "current_tier": current,
        "eta_hours": round(remaining / rate / 3600, 1) if remaining else 0,
        "paused": bool(store.get_meta("paused", False)),
        "worker": store.get_meta("worker", {"state": "not running"}),
    }
