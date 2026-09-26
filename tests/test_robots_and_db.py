"""Tests for the robots.txt guard, the DB round-trip, and secret lint."""

from __future__ import annotations

from openatlas.core.database import db_funcs
from openatlas.utils import robots, secret_lint


def test_robots_disallow(monkeypatch):
    robots._PARSER_CACHE.clear()
    disallow = "User-agent: *\nDisallow: /private"

    monkeypatch.setattr(robots, "_fetch_text", lambda *a, **k: disallow)
    assert robots.can_fetch("https://example.com/public/page") is True
    assert robots.can_fetch("https://example.com/private/secret") is False


def test_robots_absent_allows(monkeypatch):
    robots._PARSER_CACHE.clear()
    monkeypatch.setattr(robots, "_fetch_text", lambda *a, **k: None)
    assert robots.can_fetch("https://nosuchsite.example/anything") is True


def test_db_roundtrip():
    sid = db_funcs.new_session("unit-test")
    db_funcs.add_logs_to_database(sid, "verify_email_address", {"ok": True},
                                  engine_name="EmailCheckEngine", arguments={"email": "a@b.co"})
    runs = db_funcs.get_runs(sid)
    assert len(runs) == 1
    assert runs[0]["function_name"] == "verify_email_address"


def test_secret_lint_flags_paid_key():
    findings = secret_lint.scan_text('openai_api_key = "sk-abcdef0123456789abcdef"')
    assert findings, "should flag a populated paid key + sk- literal"


def test_secret_lint_clean_on_config():
    # config.py mentions key NAMES but never assigns a real value.
    findings = secret_lint.scan_path("openatlas/config.py")
    assert findings == [], f"unexpected findings: {findings}"
