"""Brain tests: taxonomy, storage/FTS, tiered ingestion against a fake MediaWiki, ask."""

from __future__ import annotations

import asyncio
import json
import urllib.parse

import httpx
import pytest

from openatlas.kb import ask, ingest, retrieve, store, taxonomy


@pytest.fixture(autouse=True)
def brain_dir(tmp_path, monkeypatch):
    from openatlas.config import Config

    monkeypatch.setattr(Config.files, "brain_dir", tmp_path / "brain")
    monkeypatch.setattr(ingest, "MIN_FREE_GB", 0.0)
    store.reset_init_cache()
    yield tmp_path / "brain"
    store.reset_init_cache()


def test_taxonomy_parses_all_divisions():
    seeds = taxonomy.parse()
    divs = taxonomy.divisions(seeds)
    assert len(divs) == 13
    assert len(seeds) > 1500  # the manifest has ~1,840 entries (~1,790 unique)
    titles = {s["title"] for s in seeds}
    assert {"Group theory", "Mathematical logic", "Carpentry", "Existential risk studies"} <= titles
    endo = next(s for s in seeds if s["title"] == "Endocrinology")
    assert len(endo["divisions"]) == 2  # deduped across divisions, both tags kept
    assert taxonomy.lookup_title("Parapsychology (as studied)") == "Parapsychology"


def test_store_chunk_search_and_update():
    text = "Group theory studies groups.\n\n" + ("Symmetry is central to group theory. " * 60)
    store.upsert_document(key="wikipedia:Group theory", source="wikipedia", title="Group theory",
                          text=text, url="https://en.wikipedia.org/wiki/Group_theory", revid=1,
                          license="CC BY-SA 4.0", tags=["domain:formal-sciences"])
    doc = store.get_document("wikipedia:Group theory")
    assert doc["chunks"] >= 2 and "domain:formal-sciences" in doc["tags"]
    hits = retrieve.search("symmetry group", k=3, use_vectors=False)
    assert hits and hits[0]["title"] == "Group theory" and hits[0]["license"].startswith("CC BY-SA")
    # Updating replaces the old chunks (no stale FTS entries).
    store.upsert_document(key="wikipedia:Group theory", source="wikipedia", title="Group theory",
                          text="Totally different content about lattices. " * 10, revid=2)
    assert not retrieve.search("symmetry", use_vectors=False)
    assert retrieve.search("lattices", use_vectors=False)


def test_clean_article_drops_reference_sections():
    raw = "Intro.\n\n== History ==\nOld.\n\n== References ==\n1. x\n\n== External links ==\ny"
    out = store.clean_article(raw)
    assert "History" in out and "References" not in out and "External links" not in out


ARTICLES = {
    "Group theory": "Group theory is the study of groups. " * 30,
    "Finite group": "A finite group is a group with finitely many elements. " * 20,
    "Mercury (disambiguation)": "Mercury may refer to...",
    "Linear algebra": "Linear algebra concerns vector spaces. " * 30,
}


def fake_mediawiki(request: httpx.Request) -> httpx.Response:
    q = dict(urllib.parse.parse_qsl(request.url.query.decode()))
    body: dict = {}
    if q.get("list") == "categorymembers":
        if q["cmtitle"] == "Category:Group theory":
            body = {"query": {"categorymembers": [
                {"ns": 0, "title": "Finite group"}, {"ns": 14, "title": "Category:Finite groups"},
                {"ns": 14, "title": "Category:Unrelated stuff"}]}}
        else:
            body = {"query": {"categorymembers": []}}
    elif q.get("list") == "allpages":
        body = {"query": {"allpages": [{"title": "Wikipedia:Vital articles/Level/4/Mathematics"}]}}
    elif q.get("prop") == "links":
        body = {"query": {"pages": [{"links": [{"title": "Linear algebra"}]}]}}
    elif q.get("prop", "").startswith("extracts"):
        title = q["titles"]
        if title not in ARTICLES:
            body = {"query": {"pages": [{"title": title, "missing": True}]}}
        else:
            dis = "disambiguation" in title
            body = {"query": {"pages": [{"title": title, "pageid": 1, "lastrevid": 42,
                                         "extract": ARTICLES[title],
                                         **({"pageprops": {"disambiguation": ""}} if dis else {})}]}}
    return httpx.Response(200, content=json.dumps(body).encode(),
                          headers={"content-type": "application/json"})


def test_tiered_ingestion(monkeypatch):
    from openatlas.net import client

    monkeypatch.setattr(client, "TRANSPORT", httpx.MockTransport(fake_mediawiki))
    seeds = [{"title": "Group theory", "namespaces": ["domain:formal-sciences"]},
             {"title": "Mercury (disambiguation)", "namespaces": ["domain:x"]},
             {"title": "Nonexistent field", "namespaces": ["domain:x"]}]
    ingest.plan(seeds, max_tier=3)
    result = asyncio.run(ingest.run(rate=1000, idle_exit=True))
    assert result["done"] >= 4 and result["skipped"] >= 2
    s = store.stats()
    assert s["documents"]["wikipedia"] == 3  # Group theory, Finite group, Linear algebra (vital)
    with store.connect() as con:
        notes = {r["title"]: (r["status"], r["note"]) for r in con.execute("SELECT * FROM queue")}
    assert notes["Mercury (disambiguation)"] == ("skipped", "disambiguation page")
    assert notes["Nonexistent field"][0] == "skipped"
    assert notes["Category:Finite groups"][0] in ("done", "pending")  # relevant subcat followed
    assert "Category:Unrelated stuff" not in notes  # irrelevant subcat ignored
    p = ingest.progress()
    assert p["percent"] == 100.0 and p["articles"] == 3


def test_pause_and_boost(monkeypatch):
    ingest.enqueue("article", "Topology", 3, priority=1)
    store.set_meta("paused", True)
    assert asyncio.run(ingest.run(rate=1000, idle_exit=True)) == {"done": 0, "skipped": 0, "failed": 0}
    store.set_meta("paused", False)
    assert ingest.boost("Topology") == 1
    assert ingest.next_task()["priority"] == 200
    assert ingest.boost("Knot theory") == 1  # unknown topic gets queued on demand
    assert ingest.next_task()["title"] in ("Topology", "Knot theory")


def test_ask_extractive_with_citations():
    store.upsert_document(key="wikipedia:Plate tectonics", source="wikipedia", title="Plate tectonics",
                          text="Plate tectonics describes the motion of Earth's lithosphere. " * 20,
                          url="https://en.wikipedia.org/wiki/Plate_tectonics", license="CC BY-SA 4.0")
    out = ask.ask("What is plate tectonics?")
    assert out["mode"] == "extractive" and out["citations"][0]["title"] == "Plate tectonics"
    none = ask.ask("zzzz qqqq")
    assert none["mode"] == "none"


def test_case_goes_into_brain():
    store.add_case({"case_id": "abc", "target": {"type": "username", "value": "janedoe"},
                    "finished_at": "now", "purpose": "self-audit",
                    "evidence": [{"status": "confirmed", "title": "GitHub: janedoe",
                                  "snippet": "designer", "source": "github",
                                  "url": "https://github.com/janedoe"}]})
    hits = retrieve.search("janedoe github", use_vectors=False)
    assert hits and hits[0]["key"] == "case:abc"
