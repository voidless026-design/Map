"""E.V's Engineering skill (adapted from everything-claude-code): code review, verification
gates, learned patterns, checkpoints, test-first feature plans and pass@k answer evals."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from openatlas.ev import agent, db, memory, tools
from openatlas.ev.skills import engineering

FAKE_KEY = "sk-" + "a1b2c3d4" * 4  # built at runtime so the repo's own secret scan stays clean

BAD = f'''import os, pickle, subprocess, sqlite3

API_KEY = "{FAKE_KEY}"


def load(blob):
    return pickle.loads(blob)


def find(con, name):
    return con.execute(f"SELECT * FROM users WHERE name = '{{name}}'")


def run(cmd):
    subprocess.run(cmd, shell=True)
    try:
        eval(cmd)
    except:
        pass
'''
CLEAN = '''def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''


@pytest.fixture(autouse=True)
def _fresh_ev(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENATLAS_EV_DOC_ROOTS", str(tmp_path / "docs"))
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    db.reset_init_cache()
    yield tmp_path / "docs"
    db.reset_init_cache()


# ------------------------------------------------------------------ review_code
def test_review_flags_the_real_problems_with_file_and_line(_fresh_ev):
    (_fresh_ev / "bad.py").write_text(BAD)
    r = tools.run("review_code", {"path": str(_fresh_ev / "bad.py")})
    assert r["ok"] and r["card"] == "review" and r["verdict"] == "block"
    what = {(f["what"], f["severity"]) for f in r["findings"]}
    assert ("hardcoded secret", "critical") in what and ("SQL built from strings", "critical") in what
    assert ("pickle.load", "high") in what and ("shell=True", "high") in what and ("eval/exec", "high") in what
    assert ("swallowed exception", "medium") in what
    assert all(f["line"] > 0 and f["why"] for f in r["findings"])
    assert r["findings"][0]["severity"] == "critical"  # worst first
    sec = tools.run("review_code", {"path": "bad.py", "focus": "security"})  # found by name too
    assert sec["ok"] and all(f["severity"] in ("critical", "high") for f in sec["findings"])


def test_review_passes_clean_code_and_flags_missing_tests_and_long_functions(_fresh_ev):
    (_fresh_ev / "clean.py").write_text(CLEAN)
    r = tools.run("review_code", {"path": str(_fresh_ev / "clean.py")})
    assert r["verdict"] == "ok" and r["findings"] == []
    pkg = _fresh_ev / "pkg"
    pkg.mkdir()
    (pkg / "big.py").write_text("def big():\n" + "    x = 1\n" * 80 + "    return x\n")
    r = tools.run("review_code", {"path": str(pkg)})
    whats = [f["what"] for f in r["findings"]]
    assert "long function big" in whats and "no tests" in whats


def test_review_refuses_files_outside_the_allowed_folders(tmp_path):
    outside = tmp_path / "secret.py"
    outside.write_text(CLEAN)
    r = tools.run("review_code", {"path": str(outside)})
    assert not r["ok"] and "outside the folders" in r["error"]


# ------------------------------------------------------------------ verify_project
def test_verify_needs_approval_then_reports_every_gate(_fresh_ev, monkeypatch):
    proj = _fresh_ev / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text("[project]\nname='p'\n")
    seen = []

    def fake(cmd, cwd, timeout):
        seen.append(cmd)
        return (1, "E   assert 2 == 3\n1 failed") if "pytest" in cmd else (0, "ok")

    monkeypatch.setattr(engineering, "RUNNER", fake)
    r = tools.run("verify_project", {"path": str(proj)})
    assert r["pending"] and not seen  # a command: nothing runs before you approve it
    done = tools.decide(r["approval"]["id"], True)
    res = done["result"]
    assert done["status"] == "done" and res["card"] == "verify" and res["passed"] is False
    gate = res["gates"][0]
    assert gate["gate"] == "tests" and not gate["passed"] and "assert 2 == 3" in gate["tail"]
    assert "not done" in res["summary"] and all(c[0] == sys.executable or c[0] == "ruff" for c in seen)


def test_verify_says_so_when_it_knows_no_checks(_fresh_ev):
    (_fresh_ev / "empty").mkdir()
    assert "no checks known" in engineering.verify_project(str(_fresh_ev / "empty"))["error"]


# ------------------------------------------------------------------ learn_pattern
def test_learning_waits_for_approval_then_can_be_recalled_and_forgotten():
    r = tools.run("learn_pattern", {"title": "Resume Kiwix downloads", "problem": "terminal closed mid-download",
                                    "solution": "run openatlas kb library resume", "when": "a .part file is left"})
    assert r["pending"] and engineering.learned() == []  # nothing saved without approval
    tools.decide(r["approval"]["id"], True)
    items = engineering.learned()
    assert len(items) == 1 and "kb library resume" in items[0]["text"] and "Use it when" in items[0]["text"]
    assert tools.run("list_learned", {"query": "kiwix"})["learned"][0]["title"] == "Resume Kiwix downloads"
    assert any("Resume Kiwix downloads" in f["text"] for f in memory.facts())  # recall finds it too
    assert not tools.run("forget_learned", {"what": " "})["ok"] and len(engineering.learned()) == 1  # never "forget all"
    assert tools.run("forget_learned", {"what": "resume kiwix"})["forgotten"] == ["Resume Kiwix downloads"]
    assert engineering.learned() == [] and not any("Resume Kiwix" in f["text"] for f in memory.facts())


# ------------------------------------------------------------------ checkpoint
def test_checkpoint_folds_the_chat_into_the_summary_and_shortens_the_context():
    cid = memory.new_conversation("long chat")
    for i in range(10):
        memory.add(cid, "user", f"question {i} about the brain")
        memory.add(cid, "assistant", f"answer {i}")
    assert len(memory.recent_for_model(cid)) == memory.KEEP_TURNS
    r = tools.run("checkpoint", {"note": "we are tuning the brain graph"}, conv_id=cid)
    assert r["checkpointed"] == 20 and "tuning the brain graph" in r["summary"]
    assert memory.conversation(cid)["summary"].startswith("Carry forward")
    assert memory.recent_for_model(cid) == []  # everything before the checkpoint lives in the summary now
    memory.add(cid, "user", "next question")
    assert [m["content"] for m in memory.recent_for_model(cid)] == ["next question"]


def test_long_chats_are_offered_a_checkpoint_not_forced():
    cid = memory.new_conversation("x")
    for i in range(40):
        memory.add(cid, "user", f"q{i}")
    assert engineering.suggest_checkpoint(cid) is True
    tools.run("checkpoint", {}, conv_id=cid)
    assert engineering.suggest_checkpoint(cid) is False


# ------------------------------------------------------------------ plan_feature
def test_feature_plans_put_tests_before_code_and_end_with_verify_and_review():
    r = tools.run("plan_feature", {"goal": "add a login page"})
    steps = [s["text"] for s in r["plan"]["steps"]]
    assert r["card"] == "plan" and len(steps) == 7
    order = [next(i for i, s in enumerate(steps) if s.startswith(k)) for k in ("Tests first", "Implement", "Verify", "Review")]
    assert order == sorted(order)


# ------------------------------------------------------------------ eval_answers
def test_pass_at_k_maths():
    assert engineering.pass_at_k([False, True, False]) == {"k": 3, "passed": 1, "pass_at_k": True, "pass_all_k": False}
    assert engineering.pass_at_k([True, True]) == {"k": 2, "passed": 2, "pass_at_k": True, "pass_all_k": True}
    assert engineering.pass_at_k([]) == {"k": 0, "passed": 0, "pass_at_k": False, "pass_all_k": False}


def test_eval_answers_with_the_local_model(fake_ollama):
    fake_ollama.replies = ["Canberra is the capital of Australia.", "Sydney is the capital of Australia.",
                           "The capital of Australia is Canberra."]
    r = tools.run("eval_answers", {"question": "What is the capital of Australia?",
                                   "expected": "Canberra is the capital city of Australia.", "k": 3})
    assert r["card"] == "eval" and r["k"] == 3 and r["passed"] == 2 and r["pass_at_k"] and not r["pass_all_k"]


def test_eval_answers_says_so_when_the_model_is_off():
    r = tools.run("eval_answers", {"question": "q", "expected": "e"})
    assert not r["ok"] and "ollama serve" in r["error"]


# ------------------------------------------------------------------ router + chat
@pytest.mark.parametrize("text,tool", [
    ("please review the code in ~/Documents/app.py", "review_code"),
    ("run the tests for ~/Documents/myproj", "verify_project"),
    ("learn from this", "learn_pattern"),
    ("checkpoint this chat", "checkpoint"),
    ("plan a feature to add login", "plan_feature"),
    ("what have we learned so far", "list_learned"),
])
def test_router_sends_engineering_asks_to_the_right_tool(text, tool):
    assert agent.route(text)[0][0] == tool


def test_chat_review_works_offline_and_shows_a_card(_fresh_ev):
    (_fresh_ev / "app.py").write_text(BAD)
    events = list(agent.respond(None, f"can you review the code in {_fresh_ev / 'app.py'}"))
    cards = [e for e in events if e["type"] == "card"]
    assert cards and cards[0]["card"] == "review" and cards[0]["verdict"] == "block"
    assert "verdict: **block**" in events[-1]["text"]


def test_an_uploaded_script_can_be_reviewed_by_name():
    from openatlas.ev.skills import documents

    documents.save_upload("upload_probe.py", BAD.encode())
    events = list(agent.respond(None, "Review the code in upload_probe.py"))
    cards = [e for e in events if e["type"] == "card"]
    assert cards and cards[0]["card"] == "review" and cards[0]["verdict"] == "block"
    with pytest.raises(ValueError):
        documents.save_upload("tool.exe", b"MZ")  # still only documents and code


def test_the_router_keeps_the_lesson_not_the_trigger_words():
    args = agent.route("learn from this: a closed terminal is fixed with openatlas kb library resume")[0][1]
    assert args["title"] == "a closed terminal is fixed with openatlas kb library resume" == args["solution"]
    assert agent.route("remember how we fixed the pause race")[0][1]["title"] == "remember how we fixed the pause race"


def test_symlinks_out_of_the_allowed_folders_are_not_read(_fresh_ev, tmp_path):
    outside = tmp_path / "private.py"
    outside.write_text(BAD)
    proj = _fresh_ev / "proj"
    proj.mkdir()
    (proj / "ok.py").write_text(CLEAN)
    (proj / "sneaky.py").symlink_to(outside)
    r = tools.run("review_code", {"path": str(proj)})
    assert r["files"] == 1 and not any(f["severity"] == "critical" for f in r["findings"])
    assert not tools.run("review_code", {"path": "sneaky"})["ok"]  # found by name, still refused
