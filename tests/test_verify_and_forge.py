"""Tests for the two skills' engines: smoke_run verifier and osint-verify."""

from __future__ import annotations

from openatlas.utils import smoke_run, verify_findings


def test_smoke_run_all_pass():
    report = smoke_run.verify_all()
    assert report["ok"], f"verification failures: {report['failed']}"
    assert report["total"] >= 40


def test_verify_username_resolves(monkeypatch):
    class _Resp:
        status_code = 200
        text = "welcome octocat profile page"

    monkeypatch.setattr(verify_findings, "scrape_get", lambda *a, **k: _Resp())
    rows = verify_findings.verify_username({"GitHub": "https://github.com/octocat"}, "octocat")
    assert rows[0]["verified"] is True
    assert rows[0]["confidence"] >= 0.8


def test_verify_username_404(monkeypatch):
    class _Resp:
        status_code = 404
        text = ""

    monkeypatch.setattr(verify_findings, "scrape_get", lambda *a, **k: _Resp())
    rows = verify_findings.verify_username({"Nope": "https://nope.example/x"}, "octocat")
    assert rows[0]["verified"] is False


def test_verify_email_no_mx():
    # real MX lookup is blocked by the _no_network fixture -> degrades to not deliverable
    rows = verify_findings.verify_email("jane@definitely-not-a-real-domain.invalid")
    assert rows[0]["verified"] in (False, None)


def test_verify_findings_summary_shape():
    report = verify_findings.run("email", claim="a@b.co")
    assert set(report["summary"]) == {"confirmed", "refuted", "unverifiable"}
