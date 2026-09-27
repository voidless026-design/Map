"""Doctor regressions: results must not depend on the folder you run it from, the brain
check must self-test on a fresh install, and unverified skills must never go live."""

from __future__ import annotations

import argparse

import pytest

from openatlas.skills import doctor, linter, registry
from openatlas.utils import forge, secret_lint

FAKE = 'api_key = "' + "sk-" + "a1b2c3d4" * 4 + '"'


# ------------------------------------------------------------------ secret lint
@pytest.mark.parametrize("layout", ["repo-root-like", "empty"])
def test_secret_lint_check_ignores_current_folder(tmp_path, monkeypatch, layout):
    # Running from ~ used to scan ~/openatlas (the whole clone incl. .venv) -> false FAIL;
    # running from a folder without ./openatlas used to scan nothing -> vacuous PASS.
    if layout == "repo-root-like":
        leak = tmp_path / "openatlas" / ".venv" / "lib" / "site-packages" / "pkg"
        leak.mkdir(parents=True)
        (leak / "example.py").write_text(FAKE)
        (tmp_path / "openatlas" / "tests").mkdir()
        (tmp_path / "openatlas" / "tests" / "t.py").write_text(FAKE)
    monkeypatch.chdir(tmp_path)
    status, detail = doctor.check_secret_lint()
    assert status == "pass", detail
    assert "source files clean" in detail and not detail.startswith("0")


def test_scan_path_skips_virtualenvs_and_honours_pragma(tmp_path):
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "x.py").write_text(FAKE)
    (tmp_path / "fixture.py").write_text(FAKE + "  # secret-lint: ignore\n")
    assert secret_lint.scan_path(tmp_path) == []
    (tmp_path / "real.py").write_text(FAKE)
    assert [f["source"].endswith("real.py") for f in secret_lint.scan_path(tmp_path)] == [True]


def test_scan_path_missing_target_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        secret_lint.scan_path(tmp_path / "nope")
    assert secret_lint.main([str(tmp_path / "nope")]) == 2


def test_default_target_is_the_package():
    assert (secret_lint.default_target() / "utils" / "secret_lint.py").exists()


# ------------------------------------------------------------------ brain
def test_brain_check_passes_on_empty_brain():
    status, detail = doctor.check_brain()
    assert status == "pass", detail
    assert "0 articles" in detail


def test_brain_check_fails_when_search_is_broken(monkeypatch):
    from openatlas.kb import retrieve

    monkeypatch.setattr(retrieve, "search", lambda *a, **k: [])
    status, detail = doctor.check_brain()
    assert status == "fail" and "self-test" in detail


def test_brain_self_test_leaves_real_brain_untouched():
    from openatlas.kb import store

    doctor.check_brain()
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_brain_check_samples_real_articles():
    from openatlas.kb import store

    store.upsert_document(key="wikipedia:Group theory", source="wikipedia", title="Group theory",
                          text="Group theory studies groups and symmetry. " * 20,
                          url="https://en.wikipedia.org/wiki/Group_theory", license="CC BY-SA 4.0")
    status, detail = doctor.check_brain()
    assert status == "pass" and "Group theory" in detail and "1 articles" in detail


# ------------------------------------------------------------------ skills
@pytest.fixture
def skill_dirs(tmp_path, monkeypatch):
    live, drafts = tmp_path / "skills", tmp_path / "skill-drafts"
    monkeypatch.setattr(registry, "skills_dir", lambda: live)
    monkeypatch.setattr(registry, "drafts_dir", lambda: drafts)
    return live, drafts


def _args(**kw):
    base = dict(name="demo-skill", description="Demo. Use when testing.", purpose="",
                trigger=["a", "b", "c"], step=None, verify=None, tool=None,
                command=["openatlas catalog"], force=False, no_commands=True)
    base.update(kw)
    return argparse.Namespace(**base)


def test_new_skill_promotes_only_after_passing(skill_dirs):
    live, drafts = skill_dirs
    assert forge.cmd_new_skill(_args()) == 0
    assert (live / "demo-skill" / "SKILL.md").exists()
    assert not (drafts / "demo-skill").exists()


def test_failing_new_skill_stays_a_draft(skill_dirs):
    live, drafts = skill_dirs
    assert forge.cmd_new_skill(_args(trigger=["only one"])) == 1  # needs >= 3 triggers
    assert (drafts / "demo-skill" / "SKILL.md").exists()
    assert not (live / "demo-skill").exists()  # never live -> doctor stays green
    # fix the draft, verify it -> promoted
    md = drafts / "demo-skill" / "SKILL.md"
    md.write_text(md.read_text().replace("- only one", "- one\n- two\n- three"))
    assert forge.cmd_verify_skill(argparse.Namespace(name="demo-skill", all=False,
                                                     no_commands=True)) == 0
    assert (live / "demo-skill" / "SKILL.md").exists() and not (drafts / "demo-skill").exists()


def test_doctor_names_the_failing_skill(skill_dirs):
    live, _ = skill_dirs
    bad = live / "half-done"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: half-done\ndescription: x\n---\n# nothing\n")
    status, detail = doctor.check_skill_linter()
    assert status == "fail" and "half-done" in detail and "skill-drafts" in detail


def test_linter_reports_unimportable_module_instead_of_crashing(tmp_path):
    d = tmp_path / "mod-ref"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: mod-ref\ndescription: d\n---\n## When to trigger\n- a\n- b\n- c\n"
        "## Verification\nx\n## Tools\nuses `openatlas.no_such_pkg.thing`\n")
    r = linter.lint_skill(str(d), run_commands=False)
    assert not r["ok"] and any("no_such_pkg" in e for e in r["errors"])
