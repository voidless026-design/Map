"""v2 user-facing surface: catalog, subcommand CLI, skills (generate + verify), web API."""

from __future__ import annotations

import json

import pytest

from openatlas import catalog, cli
from openatlas.kb import store

KEYBASE = {"them": [{"basics": {"username": "jdoe"}, "profile": {"bio": "hi"},
                     "proofs_summary": {"all": [{"proof_type": "github", "nametag": "jdoe",
                                                 "service_url": "https://github.com/jdoe",
                                                 "proof_url": "https://gist.github.com/jdoe/1"}]}}]}


@pytest.fixture(autouse=True)
def brain_dir(tmp_path, monkeypatch):
    from openatlas.config import Config

    monkeypatch.setattr(Config.files, "brain_dir", tmp_path / "brain")
    store.reset_init_cache()
    yield
    store.reset_init_cache()


# ---------------------------------------------------------------- catalog
def test_catalog_slugs_unique_and_titles_human():
    acts = catalog.actions()
    slugs = [a["slug"] for a in acts]
    assert len(slugs) == len(set(slugs))
    assert all("_" not in a["title"] for a in acts), "titles are for humans - no snake_case"
    assert "stealer-logs" not in slugs  # disabled by policy, never a button
    filters = {f["id"] for f in catalog.catalog()["filters"]}
    assert all(set(a["filters"]) <= filters for a in acts)
    assert all(a["cli"].startswith("openatlas run ") for a in acts)


def test_every_filter_has_actions():
    data = catalog.catalog()
    for f in data["filters"]:
        assert any(f["id"] in a["filters"] for a in data["actions"]), f["id"]


# ---------------------------------------------------------------- CLI
def test_cli_dispatch_from_main(capsys):
    from openatlas.main import main

    assert main(["catalog", "--filter", "username"]) == 0
    out = capsys.readouterr().out
    assert "USERNAME" in out and "whatsmyname" in out


def test_cli_investigate_json(mock_http, capsys):
    mock_http({"https://keybase.io/_/api/1.0/user/lookup.json": KEYBASE})
    rc = cli.main(["investigate", "jdoe", "--purpose", "test", "--sources", "keybase",
                   "--no-summary", "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["findings"] >= 2
    assert all(e["url"] for e in report["evidence"])


def test_cli_run_source_needs_purpose(capsys):
    assert cli.main(["run", "keybase", "jdoe"]) == 2
    assert "--purpose" in capsys.readouterr().err


def test_cli_run_unknown_slug(capsys):
    assert cli.main(["run", "no-such-thing", "x"]) == 2


def test_cli_kb_seeds_stats_pause(capsys):
    assert cli.main(["kb", "seeds"]) == 0
    assert "unique seeds" in capsys.readouterr().out
    assert cli.main(["kb", "pause"]) == 0
    assert store.get_meta("paused") is True
    assert cli.main(["kb", "resume"]) == 0
    assert store.get_meta("paused") is False
    assert cli.main(["kb", "stats", "--json"]) == 0


# ---------------------------------------------------------------- skills
def test_project_skills_all_lint_clean():
    from openatlas.skills import registry

    skills = registry.list_skills()
    names = {s["name"] for s in skills}
    assert {"skill-forge", "osint-verify", "osint-investigate", "kb-curate"} <= names
    bad = {s["name"]: s["errors"] for s in skills if not s["lint_ok"]}
    assert not bad


def test_new_skill_generates_then_verifies(tmp_path):
    from openatlas.skills import linter
    from openatlas.utils.forge import scaffold_skill

    path = scaffold_skill(
        name="demo-skill", description="Demo. Use when testing the forge.", purpose="p",
        triggers=["a", "b", "c"], steps=["do it"], verification=["check it"],
        tools=["`openatlas/utils/smoke_run.py` - dry run"], commands=["openatlas catalog"],
        root=tmp_path)
    r = linter.lint_skill(str(path.parent), run_commands=False)
    assert r["ok"], r["errors"]
    assert r["commands"][0]["command"] == "openatlas catalog"


def test_linter_rejects_bad_skill(tmp_path):
    from openatlas.skills import linter

    d = tmp_path / "Bad_Name"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: Bad_Name\ndescription: x\nmetadata:\n  project: OpenAtlas\n---\n# nope\n")
    r = linter.lint_skill(str(d), run_commands=False)
    assert not r["ok"]
    assert any("name" in e for e in r["errors"])
    assert any("trigger" in e for e in r["errors"])


def test_doctor_has_no_failures():
    from openatlas.skills import doctor

    r = doctor.run_all()
    assert r["ok"], [c for c in r["checks"] if c["status"] == "fail"]


# ---------------------------------------------------------------- web
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    with TestClient(create_app()) as c:
        yield c


def test_web_index_and_catalog(client):
    r = client.get("/")
    assert r.status_code == 200 and "OpenAtlas" in r.text
    cat = client.get("/api/catalog").json()
    assert cat["filters"] and cat["actions"]
    assert client.get("/api/detect", params={"q": "jdoe@example.com"}).json()["target"]["type"] == "email"


def test_web_rejects_foreign_host(client):
    r = client.get("/api/catalog", headers={"host": "evil.example"})
    assert r.status_code == 400


def test_web_token_required_when_set():
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    with TestClient(create_app(token="s3cret-test")) as c:
        assert c.get("/api/catalog").status_code == 401
        assert c.get("/api/catalog", headers={"x-openatlas-token": "s3cret-test"}).status_code == 200


def test_web_investigation_streams_evidence(client, mock_http):
    mock_http({"https://keybase.io/_/api/1.0/user/lookup.json": KEYBASE})
    case_id = client.post("/api/investigate", json={
        "target": "jdoe", "purpose": "unit test", "sources": ["keybase"]}).json()["case_id"]
    events = []
    with client.stream("GET", f"/api/cases/{case_id}/events") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] in ("done", "error"):
                    break
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done", types
    assert any(e["type"] == "evidence" and e["evidence"]["url"] for e in events)
    case = client.get(f"/api/cases/{case_id}").json()
    assert case["report"]["summary"]["findings"] >= 2
    md = client.get(f"/api/cases/{case_id}/markdown").text
    assert "keybase" in md.lower()


def test_web_investigate_requires_purpose(client):
    assert client.post("/api/investigate", json={"target": "x", "purpose": ""}).status_code == 422


def test_web_brain_and_skills(client):
    b = client.get("/api/brain").json()
    assert "percent" in b
    skills = client.get("/api/skills").json()
    assert any(s["name"] == "skill-forge" for s in skills)


# ---------------------------------------------------------------- brain graph (visualizer)
def test_brain_graph_grows_with_the_brain():
    from openatlas.kb import taxonomy
    from openatlas.utils import knowledge_graph

    empty = knowledge_graph.build_graph_from_brain()
    divs = [n for n in empty["nodes"] if n["id"].startswith("div_")]
    assert len(divs) == len(taxonomy.divisions(taxonomy.parse()))  # all 13 divisions
    assert all(n["status"] == "degraded" for n in divs)  # amber until something is learned

    formal, life = "domain:formal-sciences", "domain:life-sciences"
    store.upsert_document(key="wikipedia:Group theory", source="wikipedia", title="Group theory",
                          text="Group theory studies groups. " * 30, url="https://w/Group_theory",
                          tags=[formal, "tier:0"])
    store.upsert_document(key="wikipedia:Biostatistics", source="wikipedia", title="Biostatistics",
                          text="Biostatistics applies statistics to biology. " * 30,
                          url="https://w/Biostatistics", tags=[formal, life, "tier:2"])
    g = knowledge_graph.build_graph_from_brain()
    labels = {n["label"] for n in g["nodes"]}
    assert "Group theory" in labels and "Biostatistics" in labels
    assert any(lbl.startswith("Formal Sciences 2/") for lbl in labels)
    assert any(n["label"].startswith("Depth 1") for n in g["nodes"])  # grew beyond the seeds
    assert any(e["kind"] == "cross-link" for e in g["edges"])  # one article, two divisions
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])  # no dangling edges


def test_web_brain_graph_page(client):
    r = client.get("/viz/brain")
    assert r.status_code == 200
    assert "window.ATLAS_GRAPH" in r.text and "OpenAtlas brain" in r.text
