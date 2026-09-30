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
    assert "package files clean" in detail and not detail.startswith("0")


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
    (bad / "SKILL.md").write_text("---\nname: half-done\ndescription: x\nmetadata:\n  project: OpenAtlas\n---\n# nothing\n")
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


# ------------------------------------------------------------------ fixes from a real Fedora run
def test_stray_repo_copy_inside_the_package_is_skipped_and_reported(tmp_path, monkeypatch):
    """An old copy of the repo unpacked inside the package folder (with its old test fixture,
    no pragma) used to FAIL the secret lint. Now it's skipped and the doctor says what to delete."""
    pkg = tmp_path / "openatlas"
    (pkg / "tests").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "real.py").write_text("x = 1\n")
    (pkg / "tests" / "test_robots_and_db.py").write_text(FAKE)  # the old fixture line
    (pkg / "openatlas").mkdir()
    (pkg / "openatlas" / "__init__.py").write_text(FAKE)       # the package nested in itself
    assert len(secret_lint.scan_path(pkg)) == 2                 # the old behaviour
    assert secret_lint.scan_path(pkg, package=True) == []
    assert sorted(p.name for p in secret_lint.stray_copies(pkg)) == ["openatlas", "tests"]
    monkeypatch.setattr(secret_lint, "default_target", lambda: pkg)
    status, detail = doctor.check_secret_lint()
    assert status == "warn" and "mv " in detail and "~/openatlas-old-copy" in detail and "tests" in detail
    (pkg / "real.py").write_text(FAKE)                          # real package code is still scanned
    assert doctor.check_secret_lint()[0] == "fail"


def test_external_skill_is_checked_against_the_spec_only(skill_dirs):
    live, _ = skill_dirs
    (live / "developing-with-streamlit").mkdir(parents=True)
    (live / "developing-with-streamlit" / "SKILL.md").write_text(
        "---\nname: developing-with-streamlit\ndescription: Build Streamlit apps.\n---\n# Streamlit\n")
    r = linter.lint_skill(str(live / "developing-with-streamlit"), run_commands=False)
    assert r["ok"] and r["external"] and "Agent Skills spec only" in r["warnings"][0]
    (live / "bad-external").mkdir()
    (live / "bad-external" / "SKILL.md").write_text("---\nname: Not_Valid\ndescription: x\n---\n")
    assert not linter.lint_skill(str(live / "bad-external"), run_commands=False)["ok"]  # spec still enforced
    ours = live / "weak"
    ours.mkdir()
    (ours / "SKILL.md").write_text("---\nname: weak\ndescription: d\nmetadata:\n  project: OpenAtlas\n---\n")
    assert not linter.lint_skill(str(ours), run_commands=False)["ok"]  # house rules for our skills
    status, detail = doctor.check_skill_linter()
    assert status == "fail" and "Not_Valid" in detail and "weak" in detail
    import shutil

    shutil.rmtree(live / "bad-external")
    shutil.rmtree(ours)
    status, detail = doctor.check_skill_linter()
    assert status == "pass" and "external skill(s)" in detail and "developing-with-streamlit" in detail


def test_installation_check_names_missing_packages(monkeypatch):
    import importlib.util

    assert doctor.check_installation()[0] == "pass"
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a, **k: None if n == "docx" else real(n, *a, **k))
    status, detail = doctor.check_installation()
    assert status == "fail" and "python-docx" in detail and "pip install -e ." in detail
    status, detail = doctor.check_ev_documents()
    assert status == "fail" and "pip install -e ." in detail and "ModuleNotFoundError" not in detail


def test_brain_check_self_tests_tricky_titles():
    status, detail = doctor.check_brain()
    assert status == "pass", detail


def test_voice_extra_installs_on_new_python():
    """webrtcvad-wheels has no Python 3.14 wheels; if the voice extra required it there, pip
    would fail to build it and install nothing at all (the user's Fedora run)."""
    import re
    from pathlib import Path

    from openatlas.config import Config

    text = (Path(Config.files.project_root) / "pyproject.toml").read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("webrtcvad-wheels"))
    assert re.search(r'python\s*=\s*"<3\.14"', line) and "optional = true" in line


def test_link_outside_the_project_fails_installation_with_a_move_line(tmp_path, monkeypatch):
    """The user's Fedora: an old copy with its own virtualenv inside the package folder. pip
    followed its bin/python3.14 link and stopped with "... is not in the subpath of ..." """
    import sys

    pkg = tmp_path / "openatlas"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sub" / "alias.py").symlink_to(pkg / "__init__.py")  # stays inside: fine
    monkeypatch.setattr(secret_lint, "default_target", lambda: pkg)
    assert secret_lint.outside_links(pkg) == []
    assert doctor.check_installation()[0] == "pass"
    venv_bin = pkg / "openatlas" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (pkg / "openatlas" / "__init__.py").write_text("")
    (venv_bin / "python3").symlink_to(sys.executable)
    assert secret_lint.outside_links(pkg) == [venv_bin / "python3"]
    status, detail = doctor.check_installation()
    assert status == "fail" and "will fail" in detail and "python3" in detail
    assert f"mv '{pkg / 'openatlas'}' ~/openatlas-old-copy/" in detail and "rm -rf" not in detail


def test_pages_and_scripts_are_revalidated_so_updates_show():
    """Without Cache-Control Firefox kept old scripts after `git pull`."""
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    with TestClient(create_app()) as c:
        for path in ("/", "/viz/brain", "/static/ev.js", "/static/app.js"):
            r = c.get(path)
            assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path
        assert c.get("/viz/brain3d").status_code == 404  # the 3D brain is gone


def test_active_venv_inside_the_package_gets_rebuild_steps(tmp_path, monkeypatch):
    """The user's Fedora: the virtualenv in use lived in openatlas/.venv - moving it alone breaks the shell."""
    import sys

    pkg = tmp_path / "openatlas"
    (pkg / ".venv" / "bin").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / ".venv" / "bin" / "python3").symlink_to(sys.executable)
    monkeypatch.setattr(secret_lint, "default_target", lambda: pkg)
    monkeypatch.setattr(sys, "prefix", str(pkg / ".venv"))
    status, detail = doctor.check_installation()
    assert status == "fail" and "you are using" in detail and "deactivate" in detail
    assert "python3 -m venv .venv" in detail and f"mv '{pkg / '.venv'}' ~/openatlas-old-copy/" in detail
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "elsewhere"))
    status, detail = doctor.check_installation()
    assert status == "fail" and "you are using" not in detail and "mv " in detail


def test_voice_check_fails_when_the_server_cannot_open_websockets(monkeypatch):
    from openatlas.ev import voice

    monkeypatch.setattr(voice, "ws_supported", lambda: False)
    status, detail = doctor.check_ev_voice()
    assert status == "fail" and "WebSocket" in detail and "pip install -e ." in detail
