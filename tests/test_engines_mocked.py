"""Behavioural tests for representative engines, with all I/O mocked."""

from __future__ import annotations

from openatlas.core.registry import ToolResult
from openatlas.tools.email_checker import EmailCheckEngine
from openatlas.tools.get_pages import GetPagesEngine
from openatlas.tools.haveibeenpwned import HaveIBeenPwnedEngine
from openatlas.tools.ip_lookups import IPinfoEngine
from openatlas.tools.nettacker import NettackerEngine
from openatlas.tools.oathnet import OathNetEngine
from openatlas.tools.reddit_lookup import RedditKnownEngine


def test_email_syntax_invalid():
    r = EmailCheckEngine.verify_email_address("not-an-email")
    assert isinstance(r, ToolResult)
    assert r.content["valid_syntax"] is False


def test_email_valid_syntax_mx(monkeypatch):
    class _Ans:
        exchange = "mail.example.com."

    import dns.resolver

    monkeypatch.setattr(dns.resolver, "resolve", lambda *a, **k: [_Ans()])
    r = EmailCheckEngine.verify_email_address("jane@example.com")
    assert r.content["valid_syntax"] is True
    assert r.content["has_mx"] is True


def test_ip_lookup_mocked(monkeypatch):
    import openatlas.tools.ip_lookups as mod

    monkeypatch.setattr(mod, "api_get_json",
                        lambda *a, **k: {"status": "success", "country": "US", "query": "8.8.8.8"})
    r = IPinfoEngine.basic_ip_lookup("8.8.8.8")
    assert r.success and r.content["country"] == "US"


def test_reddit_about_mocked(monkeypatch):
    import openatlas.tools.reddit_lookup as mod

    monkeypatch.setattr(mod, "api_get_json",
                        lambda *a, **k: {"data": {"name": "octocat", "comment_karma": 5}})
    r = RedditKnownEngine.fetch_about("octocat")
    assert r.success and r.content["name"] == "octocat"


def test_reddit_unreachable_degrades(monkeypatch):
    import openatlas.tools.reddit_lookup as mod

    monkeypatch.setattr(mod, "api_get_json", lambda *a, **k: None)
    r = RedditKnownEngine.fetch_comments("octocat")
    assert not r.success and r.error  # graceful, with an error string


def test_getpage_robots_blocked(monkeypatch):
    import openatlas.tools.get_pages as mod

    monkeypatch.setattr(mod, "scrape_get", lambda *a, **k: None)
    r = GetPagesEngine.fetch_get_page("https://example.com")
    assert not r.success and r.error


def test_breach_check_mocked(monkeypatch):
    import openatlas.tools.haveibeenpwned as mod

    monkeypatch.setattr(mod, "api_get_json", lambda *a, **k: {"breaches": [["Adobe", "LinkedIn"]]})
    r = HaveIBeenPwnedEngine.check_email_against_breach_data("jane@example.com")
    assert r.success and r.content["found"] is True


def test_nettacker_refuses_without_authorization():
    r = NettackerEngine.nettacker_run(["example.com"], authorized=False)
    assert not r.success
    assert r.error == "authorization-required"


def test_stealer_logs_disabled_by_policy():
    r = OathNetEngine.get_stealer_logs("anything")
    assert not r.success
    assert r.error == "disabled-by-policy"
