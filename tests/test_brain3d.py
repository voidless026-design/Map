"""The 3D brain: hubs per division, neurons with inspectable detail, synapses, the node cap."""

from __future__ import annotations

from openatlas.kb import store, taxonomy
from openatlas.utils import knowledge_graph


def _brain(n=60):
    seeds = taxonomy.parse()[:n]
    store.upsert_many([{"key": f"wikipedia:{s['title']}", "source": "wikipedia", "title": s["title"],
                        "text": f"{s['title']} is studied in {s['divisions'][0]}. " * 3, "license": "CC BY-SA 4.0",
                        "tags": list(s["namespaces"]) + ["seed", "tier:0"]} for s in seeds])
    store.upsert_document(key="wikipedia:Kiwix only", source="wikipedia", title="Kiwix only",
                          text="From a ZIM file. " * 5, tags=["kiwix:wikipedia_en_all_nopic"])
    return seeds


def test_graph_shape_and_detail():
    seeds = _brain()
    g = knowledge_graph.build_brain3d()
    kinds = {n["kind"] for n in g["nodes"]}
    assert kinds == {"core", "hub", "neuron"}
    neurons = [n for n in g["nodes"] if n["kind"] == "neuron"]
    assert len(neurons) == len(seeds) + 1 and g["meta"]["articles"] == len(seeds) + 1
    n = next(x for x in neurons if x["label"] == seeds[0]["title"])
    assert n["division"] == seeds[0]["divisions"][0] and n["seed"] and n["tier"] == 0
    assert n["snippet"].startswith(seeds[0]["title"]) and n["license"] == "CC BY-SA 4.0" and n["degree"] >= 1
    ids = {x["id"] for x in g["nodes"]}
    assert all(ln["source"] in ids and ln["target"] in ids for ln in g["links"])
    assert any(x["label"] == "Kiwix: wikipedia_en_all_nopic" for x in g["nodes"] if x["kind"] == "hub")
    assert any(ln["kind"] == "area" for ln in g["links"])  # related topics chained


def test_node_cap_keeps_seeds_first():
    _brain(80)
    g = knowledge_graph.build_brain3d(limit=50)
    neurons = [n for n in g["nodes"] if n["kind"] == "neuron"]
    assert len(neurons) == 50 and all(n["seed"] for n in neurons) and g["meta"]["shown"] == 50


def test_endpoints():
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    seeds = _brain(10)
    with TestClient(create_app()) as c:
        assert "brain3d.js" in c.get("/viz/brain3d").text
        g = c.get("/api/brain/graph3d?limit=100").json()
        key = next(n["key"] for n in g["nodes"] if n.get("kind") == "neuron")
        art = c.get("/api/brain/article", params={"key": key}).json()
        assert art["title"] in {s["title"] for s in seeds} | {"Kiwix only"} and art["text"]
        assert c.get("/api/brain/article", params={"key": "nope"}).status_code == 404
        assert c.get("/static/vendor/brain3d.vendor.js").status_code == 200
