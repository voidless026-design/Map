"""Investigation pipeline tests against a fake web (no real network)."""

from __future__ import annotations

import asyncio

import pytest

from openatlas.investigate import extract, pipeline, report, sources
from openatlas.investigate.detect import detect
from openatlas.investigate.sources import usernames as wmn


@pytest.mark.parametrize("raw,kind", [
    ("jane.doe@example.com", "email"), ("janedoe_42", "username"), ("@janedoe", "username"),
    ("Jane Doe", "name"), ("+1 415 555 0132", "phone"), ("example.com", "domain"),
    ("https://example.com/about", "url"), ("8.8.8.8", "ip"), ("photo.jpg", "image"),
])
def test_detect(raw, kind):
    assert detect(raw).type == kind


def test_detect_normalises():
    assert detect("@JaneDoe").value == "JaneDoe"
    assert detect("Jane.Doe@Example.COM").value == "jane.doe@example.com"
    assert "Doe, Jane" in detect("Jane Doe").variants


def test_extract_page_text_and_entities():
    html = """<html><head><title>About Jane</title><script>var x=1</script></head><body>
      <nav>menu</nav><p>Jane Doe is a designer. Contact jane.doe@studio.io or +1 (415) 555-0132.
      Find her as @janedoe_art.</p><a href="https://github.com/janedoe">gh</a></body></html>"""
    title, text, links = extract.page_text(html)
    assert title == "About Jane" and "var x" not in text and "menu" not in text
    ents = {(e["type"], e["value"].lower()) for e in extract.entities_near(text, ["Jane Doe"])}
    assert ("email", "jane.doe@studio.io") in ents
    assert ("username", "janedoe_art") in ents
    assert any(t == "phone" for t, _ in ents)
    assert extract.social_profile(links[0])["handle"] == "janedoe"
    assert extract.social_profile("https://twitter.com/intent/tweet") is None


def test_whatsmyname_classify_and_sweep(monkeypatch, mock_http):
    sites = [
        {"name": "Alpha", "uri_check": "https://alpha.example/u/{account}", "e_code": 200,
         "e_string": "Profile of", "m_code": 404, "m_string": "Not found", "cat": "social"},
        {"name": "Beta", "uri_check": "https://beta.example/{account}", "e_code": 200,
         "e_string": "Profile of", "m_code": 404, "m_string": "Not found", "cat": "social"},
        {"name": "Gamma", "uri_check": "https://gamma.example/api", "cat": "tech",
         "post_body": '{"user":"{account}"}', "headers": {"Content-Type": "application/json"},
         "e_code": 200, "e_string": '"exists":true', "m_code": 200, "m_string": '"exists":false'},
        {"name": "Adult", "uri_check": "https://nsfw.example/{account}", "cat": "xx NSFW xx",
         "e_code": 200, "e_string": "x", "m_code": 404, "m_string": "y"},
        {"name": "Broken", "uri_check": "https://broken.example/{account}", "valid": False,
         "e_code": 200, "e_string": "x", "m_code": 404, "m_string": "y", "cat": "misc"},
        {"name": "Dots", "uri_check": "https://dots.example/{account}", "strip_bad_char": ".",
         "e_code": 200, "e_string": "Profile of", "m_code": 404, "m_string": "Not found", "cat": "misc"},
    ]
    monkeypatch.setattr(wmn, "load_sites", lambda: sites)
    mock_http({
        "https://alpha.example/u/jane.doe": "<h1>Profile of jane.doe</h1>",
        "https://beta.example/": (404, "Not found"),
        "https://gamma.example/api": (200, '{"exists":true}'),
        "https://dots.example/janedoe": "<h1>Profile of janedoe</h1>",
    })
    from openatlas.net.client import Net

    async def go():
        async with Net() as net:
            return await wmn.sweep("jane.doe", net)

    res = {r["site"]: r["status"] for r in asyncio.run(go())}
    assert res == {"Alpha": "found", "Beta": "not_found", "Gamma": "found", "Dots": "found"}


GITHUB_USER = {"login": "janedoe", "name": "Jane Doe", "html_url": "https://github.com/janedoe",
               "blog": "https://janedoe.dev", "location": "Lisbon", "twitter_username": "janedoe_art",
               "public_repos": 12}


@pytest.fixture
def fake_web(monkeypatch, mock_http):
    """A tiny consistent public footprint for the username 'janedoe'."""
    sites = [
        {"name": "Alpha", "uri_check": "https://alpha.example/u/{account}", "e_code": 200,
         "e_string": "Profile of", "m_code": 404, "m_string": "Not found", "cat": "social"},
        {"name": "Ghost", "uri_check": "https://ghost.example/{account}", "e_code": 200,
         "e_string": "", "m_code": 404, "m_string": "Not found", "cat": "social"},
    ]
    monkeypatch.setattr(wmn, "load_sites", lambda: sites)
    from openatlas.investigate.sources import websearch

    monkeypatch.setattr(websearch, "_ddg", lambda q, n: [
        {"title": "Jane Doe - portfolio", "url": "https://janedoe.dev/about",
         "snippet": "janedoe designs things"},
        {"title": "Old forum post", "url": "https://forum.example/t/1", "snippet": "janedoe said"},
        {"title": "Jane Doe | Spokeo", "url": "https://www.spokeo.com/Jane-Doe", "snippet": "janedoe"},
    ])
    mock_http({
        "https://alpha.example/u/janedoe": "<h1>Profile of janedoe</h1>",
        "https://ghost.example/janedoe": "<html>Welcome</html>",  # claims a hit; page lacks the name
        "https://api.github.com/users/janedoe": GITHUB_USER,
        "https://keybase.io/_/api/1.0/user/lookup.json": {"them": [{
            "basics": {"username": "janedoe"}, "profile": {"bio": "designer"},
            "proofs_summary": {"all": [{"proof_type": "github", "nametag": "janedoe",
                                        "service_url": "https://github.com/janedoe",
                                        "proof_url": "https://gist.github.com/janedoe/1"}]}}]},
        "https://hacker-news.firebaseio.com/v0/user/janedoe.json": (200, "null"),
        "https://hn.algolia.com/api/v1/search": {"hits": []},
        "https://janedoe.dev/about": "<html><title>About</title><body><p>Hi, I'm janedoe. "
                                     "Mail me: hello@janedoe.dev</p></body></html>",
        "https://forum.example/t/1": "<html><body>This thread was deleted.</body></html>",
    })


def _run(**kw):
    events = []
    rep = asyncio.run(pipeline.run_investigation(
        "janedoe", purpose="self-audit of my own footprint", emit=events.append,
        source_ids=["web-search", "whatsmyname", "github", "keybase", "hackernews"],
        summarize=False, **kw))
    return rep, events


def test_pipeline_end_to_end(fake_web):
    rep, events = _run()
    ev = {e["title"]: e for e in rep["evidence"]}

    # Every finding carries a status and (where relevant) a link - no bare booleans.
    assert all(e["status"] in ("confirmed", "refuted", "unverified") for e in rep["evidence"])
    # First-party APIs are confirmed; the profile page re-check confirms Alpha...
    assert ev["GitHub: janedoe (Jane Doe)"]["status"] == "confirmed"
    assert ev["Alpha: account 'janedoe' exists"]["status"] == "confirmed"
    # ...and the page that doesn't actually show the username stays unconfirmed.
    assert ev["Ghost: account 'janedoe' exists"]["status"] == "unverified"
    # Reading pages: portfolio confirmed + email extracted; deleted thread refuted.
    assert ev["Jane Doe - portfolio"]["status"] == "confirmed"
    assert ev["Old forum post"]["status"] == "refuted"
    assert any(e["entity_value"] == "hello@janedoe.dev" for e in rep["evidence"])
    # Data brokers are never opened.
    assert ev["Jane Doe | Spokeo"]["status"] == "unverified"
    # Correlation: the GitHub account is corroborated by the Keybase proof.
    gh = [e for e in rep["entities"] if e["value"] == "janedoe" and e["type"] == "username"][0]
    assert {"github", "keybase"} <= set(gh["sources"])
    # Transparency: what was searched is listed, with outcomes.
    assert {r["source"] for r in rep["searched"]} >= {"whatsmyname", "github", "keybase"}
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done" and "evidence" in types


def test_pipeline_persists_case(fake_web):
    from openatlas.core.database import db_funcs

    rep, _ = _run()
    saved = db_funcs.get_case(rep["case_id"])
    assert saved["status"] == "done" and saved["purpose"].startswith("self-audit")
    assert db_funcs.seen_before("email", "hello@janedoe.dev", exclude_case="other")


def test_purpose_is_required():
    with pytest.raises(ValueError):
        asyncio.run(pipeline.run_investigation("janedoe", purpose="  ", persist=False))


def test_slow_source_times_out(monkeypatch):
    from openatlas.investigate.models import SourceResult

    async def slow(t, net):
        await asyncio.sleep(5)
        return SourceResult("slow", ok=True, searched="x")

    monkeypatch.setitem(sources.SOURCES, "slow", sources.SourceSpec(
        "slow", "Slow", "sleeps", ("username",), ("username",), slow, timeout=0.2))
    rep = asyncio.run(pipeline.run_investigation("janedoe", purpose="test", source_ids=["slow"],
                                                 persist=False, summarize=False))
    assert rep["searched"][0]["error"].startswith("timed out")


def test_markdown_report(fake_web):
    rep, _ = _run()
    md = report.to_markdown(rep)
    assert "## Findings" in md and "## What was searched" in md and "✓" in md
