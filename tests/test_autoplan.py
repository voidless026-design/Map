"""ATLAS loop wired into v2: Auto-plan (plan) and the post-case check + repair step."""

from __future__ import annotations

import json

import pytest

from openatlas.llm import ollama_client
from openatlas.reasoning import loop


def test_heuristic_plan_uses_recommended_sources():
    p = loop.plan_case("jdoe_42", "due diligence")
    assert p["mode"] == "heuristic" and p["target"]["type"] == "username"
    assert "whatsmyname" in p["steps"] and "keybase" in p["steps"]
    assert set(p["steps"]) <= set(p["available"])


def test_self_audit_adds_opt_in_checks():
    other = loop.plan_case("jane@example.com", "due diligence")
    mine = loop.plan_case("jane@example.com", "Self-audit (my own footprint)")
    assert "holehe" not in other["steps"] and "holehe" in mine["steps"]
    assert "an email" in mine["why"]


@pytest.fixture
def llm(monkeypatch):
    def install(answer):
        monkeypatch.setattr(ollama_client, "available", lambda *a, **k: True)
        monkeypatch.setattr(ollama_client, "complete", lambda *a, **k: answer)
    return install


def test_local_ai_plan_is_filtered_to_real_fitting_sources(llm):
    llm(json.dumps({"steps": ["keybase", "rdap", "not-a-source", "keybase", "github"],
                    "why": "proofs first"}))
    p = loop.plan_case("jdoe_42", "research")
    assert p["mode"] == "local-ai"
    assert p["steps"] == ["keybase", "github"]  # rdap doesn't fit a username; dupes/unknowns dropped


@pytest.mark.parametrize("answer", ["no json here", '{"steps": ["nope"]}', ""])
def test_unusable_ai_answer_falls_back_to_heuristic(llm, answer):
    llm(answer)
    p = loop.plan_case("jdoe_42", "research")
    assert p["mode"] == "heuristic" and p["steps"]


REPORT = {
    "case_id": "abc", "purpose": "test", "target": {"type": "username", "value": "jdoe_42"},
    "summary": {"confirmed": 3, "unverified": 1, "refuted": 0, "findings": 4,
                "sources_ok": 2, "sources_failed": 1},
    "searched": [{"source": "github", "ok": True}, {"source": "reddit", "ok": False},
                 {"source": "keybase", "ok": True}],
    "entities": [
        {"type": "email", "value": "jane@example.org", "sources": ["github"], "confirmed": True},
        {"type": "username", "value": "JDOE_42", "sources": ["a", "b"], "confirmed": True},  # itself
        {"type": "url", "value": "https://jdoe.example", "sources": ["github", "keybase"],
         "confirmed": False},
        {"type": "username", "value": "maybe", "sources": ["web-search"], "confirmed": False},
    ],
}


def test_check_proposes_retry_and_pivots():
    k = loop.check_case(REPORT)
    assert k["mode"] == "heuristic" and k["retry"] == ["reddit"]
    assert [p["value"] for p in k["pivots"]] == ["jane@example.org", "https://jdoe.example"]
    assert "1 failed" in k["assessment"] and "2 new identifier" in k["assessment"]


def test_check_uses_local_ai_assessment_when_available(llm):
    llm("Purpose met; retry Reddit and follow the email.")
    k = loop.check_case(REPORT)
    assert k["mode"] == "local-ai" and k["assessment"].startswith("Purpose met")
    assert k["retry"] == ["reddit"]  # the repair round itself stays deterministic


def test_web_plan_and_check(tmp_path, monkeypatch, mock_http):
    from fastapi.testclient import TestClient

    from openatlas.config import Config
    from openatlas.kb import store
    from openatlas.web.server import create_app

    monkeypatch.setattr(Config.files, "brain_dir", tmp_path / "brain")
    store.reset_init_cache()
    mock_http({"https://keybase.io/_/api/1.0/user/lookup.json": {"them": []}})
    with TestClient(create_app()) as c:
        p = c.post("/api/plan", json={"target": "jdoe_42", "purpose": "test"}).json()
        assert p["steps"] and p["target"]["type"] == "username"
        assert c.get("/api/cases/nope/check").status_code == 404
        case_id = c.post("/api/investigate", json={"target": "jdoe_42", "purpose": "unit test",
                                                    "sources": ["keybase"]}).json()["case_id"]
        with c.stream("GET", f"/api/cases/{case_id}/events") as r:
            for line in r.iter_lines():
                if line.startswith("data: ") and json.loads(line[6:])["type"] in ("done", "error"):
                    break
        k = c.get(f"/api/cases/{case_id}/check").json()
        assert "assessment" in k and k["retry"] == [] and isinstance(k["pivots"], list)


def test_cli_plan(capsys):
    from openatlas import cli

    assert cli.main(["plan", "jdoe_42", "--purpose", "research"]) == 0
    out = capsys.readouterr().out
    assert "Auto-plan (heuristic)" in out and "openatlas investigate jdoe_42 --sources" in out
    assert cli.main(["plan", "8.8.8.8", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["target"]["type"] == "ip"
