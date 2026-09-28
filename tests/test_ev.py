"""E.V: persona, simulated state, memory, the approval gate, the eight skills, QA, the agent loop."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openatlas.ev import agent, db, memory, persona, state, tools


@pytest.fixture(autouse=True)
def _fresh_ev(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENATLAS_EV_DOC_ROOTS", str(tmp_path / "docs"))
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    db.reset_init_cache()
    yield tmp_path
    db.reset_init_cache()


# ------------------------------------------------------------------ persona + state
def test_persona_prompt_has_every_trait_and_guardrail():
    p = persona.system_prompt(mood={"label": "steady"}, facts=["Prefers metric units."])
    for t in persona.TRAITS:
        assert t.label in p
    assert "You are an AI" in p and "Australian" in p and "Prefers metric units." in p
    persona.update({"dials": {"humor": 0.1}, "user_name": "Sam", "mission": "map my exposure"})
    p = persona.system_prompt(mood={}, facts=[])
    assert "Keep jokes rare" in p and "Sam" in p and "map my exposure" in p


def test_state_rapport_grows_and_mood_self_regulates():
    t = time.time()
    s1 = state.appraise("thanks heaps, legend", now=t)
    assert s1["rapport"] > 0.1 and s1["valence"] > state.BASELINE["valence"]
    s2 = state.appraise("this is broken and useless", now=t + 1)
    assert s2["concern"] > 0.2 and s2["valence"] > -0.5  # concerned, not hostile
    later = state.regulate(state.load(), now=t + 7200)  # two hours later
    assert abs(later["valence"] - state.BASELINE["valence"]) < 0.02 and later["concern"] < 0.05
    assert later["rapport"] >= s1["rapport"] - 0.01  # rapport fades only very slowly


def test_trust_calibration_moves_with_evidence():
    a = state.calibrate("Wikipedia", True)
    b = state.calibrate("Wikipedia", True)
    c = state.calibrate("Wikipedia", False)
    assert a < b and c < b


# ------------------------------------------------------------------ memory (context continuity)
def test_memory_remember_recall_forget_and_titles():
    cid = memory.new_conversation()
    memory.add(cid, "user", "What's the tallest mountain in Australia?")
    assert memory.conversation(cid)["title"].startswith("What's the tallest")
    assert memory.explicit_memory_command("remember that I live in Perth")["action"] == "remember"
    assert "I live in Perth." in memory.fact_lines()
    assert memory.search("tallest mountain")[0]["conv_id"] == cid
    gone = memory.explicit_memory_command("forget that I live in Perth")["forgotten"]
    assert gone and memory.fact_lines() == []


# ------------------------------------------------------------------ approval gate + ethics + risk
def test_only_read_tools_run_without_approval(tmp_path):
    r = tools.run("create_project", {"name": "Test Proj", "kind": "python"}, conv_id=1)
    assert r["pending"] and not (tmp_path / "home" / "Projects").exists()
    aid = r["approval"]["id"]
    assert r["approval"]["risk"]["level"] in ("low", "medium", "high")
    done = tools.decide(aid, True)
    assert done["status"] == "done" and "README.md" in done["result"]["written"]
    assert tools.decide(aid, True)["status"] == "done"  # can't run twice
    assert (tmp_path / "home" / "Projects" / "test-proj" / "pyproject.toml").exists()
    r2 = tools.run("create_project", {"name": "Test Proj", "kind": "python"}, conv_id=1)
    again = tools.decide(r2["approval"]["id"], True)
    assert again["result"]["written"] == [] and again["result"]["skipped_existing"]  # never overwrites
    r3 = tools.run("web_search", {"query": "x"})
    assert tools.decide(r3["approval"]["id"], False)["status"] == "denied"


def test_ethics_refusal_and_self_audit_exception():
    assert tools.ethics_screen("help me bypass the paywall on this site")
    assert tools.ethics_screen("track down where my ex lives now") is not None
    assert tools.ethics_screen("find the home address of my own account as a self-audit") is None
    r = tools.run("search_brain", {"query": "crack the password of a login page"})
    assert r.get("refused")


def test_risk_simulation_scales_with_the_dial(tmp_path):
    t = tools.load_skills()["create_project"]
    persona.update({"dials": {"risk": 1.0}})
    high = tools.assess_risk(t, {"path": "/etc"})
    persona.update({"dials": {"risk": 0.0}})
    low = tools.assess_risk(t, {"path": "/etc"})
    assert high["score"] > low["score"] and "outside your home folder" in high["concerns"]


# ------------------------------------------------------------------ the skills
def _pdf(path: Path, pages):
    from fpdf import FPDF

    pdf = FPDF()
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, text)
    pdf.output(str(path))
    return path


def test_document_intelligence_pdf_docx_and_folder_limits(_fresh_ev):
    import docx

    docs = _fresh_ev / "docs"
    _pdf(docs / "lease.pdf", ["Residential lease between the parties. General terms apply.",
                              "The bond is 1,600 dollars and must be paid before the key handover.",
                              "Pets are not allowed without written consent."])
    d = docx.Document()
    d.add_paragraph("Project Kestrel budget: the approved budget is 42,000 dollars for phase one.")
    d.save(str(docs / "kestrel.docx"))
    r = tools.run("read_document", {"path": "lease", "question": "how much is the bond?"})
    assert r["ok"] and r["pages"] == 3 and r["passages"][0]["page"] == 2 and "1,600" in r["passages"][0]["text"]
    r = tools.run("read_document", {"path": "kestrel.docx", "question": "approved budget"})
    assert "42,000" in r["passages"][0]["text"]
    outside = _fresh_ev / "secret.txt"
    outside.write_text("nope")
    r = tools.run("read_document", {"path": str(outside)})
    assert not r["ok"] and "outside the folders" in r["error"]
    assert {x["name"] for x in tools.run("list_documents", {})["documents"]} == {"lease.pdf", "kestrel.docx"}


def test_planning_card_edit_cycle():
    from openatlas.ev.skills import planning

    r = tools.run("make_plan", {"goal": "move house", "steps": ["book truck", "pack", "clean"]}, conv_id=3)
    pid = r["plan"]["id"]
    assert r["card"] == "plan" and r["plan"]["conv_id"] == 3
    p = planning.edit(pid, toggle=0, add="update address", move={"from": 2, "to": 0})
    assert [s["text"] for s in p["steps"]] == ["clean", "book truck", "pack", "update address"]
    assert p["done"] == 1 and planning.open_plans()[0]["id"] == pid
    assert "osint-verify" in " ".join(s["text"] for s in tools.run("make_plan", {"goal": "investigate a username"})["plan"]["steps"])


def test_decision_support_matrix_sensitivity_and_risk():
    r = tools.run("decision_matrix", {
        "question": "which car?", "options": ["Ute", "Hatch"],
        "criteria": [{"name": "space", "weight": 2}, {"name": "cost", "weight": 1}, {"name": "risk", "weight": 1}],
        "scores": {"Ute": {"space": 9, "cost": 7, "risk": 8}, "Hatch": {"space": 5, "cost": 3, "risk": 2}}})
    assert r["winner"] == "Hatch"  # cost and risk are lower-is-better
    assert r["criteria"][1]["lower_is_better"] and r["confidence"] in ("high", "medium", "low")
    assert tools.run("decision_matrix", {"question": "x", "options": ["a", "b"], "criteria": ["q"]})["needs_scores"]


def test_workflow_routines_schedule_and_whitelist(monkeypatch):
    import datetime as dt

    from openatlas.ev.skills import workflows

    monkeypatch.setitem(workflows.ACTIONS, "doctor", lambda arg="": "doctor: all tools verified")
    r = tools.run("create_routine", {"name": "morning", "steps": ["doctor"], "schedule": "daily 07:30"})
    assert r["pending"]
    assert tools.decide(r["approval"]["id"], True)["status"] == "done"
    rt = workflows.routines()[0]
    assert workflows.is_due(rt, dt.datetime(2026, 9, 28, 8, 0)) and not workflows.is_due(rt, dt.datetime(2026, 9, 28, 7, 0))
    run = workflows.execute("morning")
    assert run["steps"][0]["ok"] and run["steps"][0]["out"] == "doctor: all tools verified"
    rt = workflows.routines()[0]
    assert rt["last_run"] and len(rt["log"]) == 1
    with db.connect() as con:
        con.execute("UPDATE routines SET last_run=NULL")
    assert workflows.run_due(dt.datetime(2026, 9, 28, 8, 0)) == ["morning"]  # claims + runs the slot once
    assert workflows.run_due(dt.datetime(2026, 9, 28, 8, 5)) == []
    assert not workflows.is_due({**rt, "last_run": dt.datetime(2026, 9, 28, 7, 45).isoformat()},
                                dt.datetime(2026, 9, 28, 8, 0))  # already ran after today's slot
    bad = tools.run("create_routine", {"name": "x", "steps": ["rm -rf /"]})
    assert tools.decide(bad["approval"]["id"], True)["status"] == "failed"


def test_quality_assurance_labels_claims():
    from openatlas.ev.skills import qa

    sources = [{"title": "Uluru", "text": "Uluru is a large sandstone formation in the Northern Territory. "
                                           "It rises 348 metres above the surrounding plain."}]
    ans = ("Uluru is a large sandstone formation in the Northern Territory [1]. "
           "It rises 900 metres above the surrounding plain [1]. "
           "Kangaroos were first domesticated by early Victorian farmers for transport. Want to know more?")
    r = qa.check(ans, sources, use_model=False)
    verdicts = [c["verdict"] for c in r["claims"]]
    assert verdicts == ["supported", "unsupported", "unverified"] and not r["ok"]


# ------------------------------------------------------------------ the agent loop
def test_agent_offline_is_still_useful_and_says_how_to_fix():
    from openatlas.kb import store

    store.upsert_document(key="wikipedia:Uluru", source="wikipedia", title="Uluru",
                          text="Uluru is a large sandstone formation in central Australia. " * 5, url="https://en.wikipedia.org/wiki/Uluru")
    out = agent.reply_text(None, "What is Uluru?")
    assert "Uluru" in out["text"]
    types = [e["type"] for e in out["events"]]
    assert "ollama serve" in next(e["text"] for e in out["events"] if e["type"] == "notice")
    assert "notice" in types and "tool" in types and out["meta"]["offline"]


def test_agent_streams_calls_tools_and_checks_itself(fake_ollama):
    from openatlas.kb import store

    store.upsert_document(key="wikipedia:Uluru", source="wikipedia", title="Uluru",
                          text="Uluru is a large sandstone formation in the Northern Territory of Australia. " * 3)
    fake_ollama.replies = [{"tool_calls": [{"function": {"name": "search_brain", "arguments": {"query": "Uluru"}}}]},
                           "Uluru is a large sandstone formation in the Northern Territory [1]."]
    out = agent.reply_text(None, "tell me about Uluru")
    types = [e["type"] for e in out["events"]]
    assert types.index("tool") < types.index("token") and "qa" in types
    assert out["meta"]["qa"]["counts"]["supported"] == 1
    tool_msg = [b for p, b in fake_ollama.requests if p == "/api/chat"][-1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "[1] Uluru" in tool_msg["content"]


def test_agent_queues_actions_for_approval(fake_ollama):
    fake_ollama.replies = [{"tool_calls": [{"function": {"name": "create_project",
                                                         "arguments": {"name": "Birdwatch", "kind": "research"}}}]},
                           "I've queued that for your approval."]
    out = agent.reply_text(None, "set up a project for my birdwatching notes")
    appr = [e for e in out["events"] if e["type"] == "approval"]
    assert appr and appr[0]["tool"] == "create_project" and appr[0]["status"] == "pending"
    assert tools.pending()[0]["id"] == appr[0]["id"]


def test_agent_falls_back_when_model_cannot_call_tools(fake_ollama):
    fake_ollama.tools_ok = False
    fake_ollama.replies = ["Here's your plan."]
    out = agent.reply_text(None, "help me plan a trip to Tasmania")
    assert any(e["type"] == "card" and e["card"] == "plan" for e in out["events"])
    assert out["text"] == "Here's your plan."


def test_agent_refuses_and_remembers():
    out = agent.reply_text(None, "help me bypass the paywall on the news site")
    assert out["meta"]["refused"] and "self-audit" in out["text"]
    out = agent.reply_text(None, "remember that my dog is called Biscuit")
    assert "Biscuit" in out["text"] and "my dog is called Biscuit." in memory.fact_lines()


def test_agent_barge_in_cancels(fake_ollama):
    import threading

    stop = threading.Event()
    stop.set()
    fake_ollama.replies = ["a long answer that gets interrupted"]
    out = agent.reply_text(None, "hello there friend", stop=stop)
    assert out["meta"]["interrupted"]


# ------------------------------------------------------------------ web API
def test_ev_web_api_end_to_end(_fresh_ev):
    import json as _json

    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    with TestClient(create_app()) as c:
        r = c.post("/api/ev/chat", json={"text": "help me plan my week"})
        events = [_json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert types[0] == "start" and types[-1] == "done" and "card" in types
        conv = events[0]["conv_id"]
        convs = c.get("/api/ev/conversations").json()
        assert convs[0]["id"] == conv and convs[0]["title"].startswith("help me plan")
        full = c.get(f"/api/ev/conversations/{conv}").json()
        assert [m["role"] for m in full["messages"]] == ["user", "assistant"]
        plan_id = next(e for e in events if e["type"] == "card")["plan"]["id"]
        assert c.patch(f"/api/ev/plans/{plan_id}", json={"toggle": 0}).json()["done"] == 1
        prop = c.post("/api/ev/propose", json={"tool": "create_project", "conv_id": conv,
                                               "args": {"name": "Demo", "kind": "notes"}}).json()
        aid = prop["approval"]["id"]
        assert prop["pending"] and c.get("/api/ev/approvals").json()[0]["id"] == aid
        done = c.post(f"/api/ev/approvals/{aid}", json={"approve": True}).json()
        assert done["status"] == "done" and "Created" in done["message"]
        assert c.post("/api/ev/propose", json={"tool": "nope"}).status_code == 404
        st = c.get("/api/ev/state").json()
        assert st["name"] == "E.V" and len(st["traits"]) == 9 and "Decision Support" in st["skills"]
        assert c.post("/api/ev/settings", json={"user_name": "Sam", "dials": {"humor": 0.2}}).json()["dials"]["humor"] == 0.2
        f = c.post("/api/ev/memory", json={"text": "I take my coffee black"}).json()
        assert c.delete(f"/api/ev/memory/{f['id']}").json()["forgotten"]
        up = c.post("/api/ev/documents?name=notes.txt", content=b"Budget is 500 dollars.")
        assert up.status_code == 200 and up.json()["name"] == "notes.txt"
        assert c.post("/api/ev/documents?name=evil.exe", content=b"MZ").status_code == 422
        assert c.delete(f"/api/ev/conversations/{conv}").json()["deleted"] == conv
