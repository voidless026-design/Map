"""Shared test fixtures. All network and LLM access is mocked - tests never go online."""

from __future__ import annotations

import pytest

from openatlas.core.database import db_funcs


@pytest.fixture(autouse=True)
def _in_memory_db():
    """Point the DB layer at a fresh in-memory SQLite for every test."""
    db_funcs.reset_for_tests()
    yield


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test accidentally makes a real HTTP call."""
    import requests

    def _blocked(*a, **k):  # pragma: no cover
        raise AssertionError("network access attempted in a test; mock it instead")

    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked, raising=False)

    # httpx (used by the v2 net client and the Ollama client): every request fails with a
    # ConnectError unless a test installs its own MockTransport via `mock_http`.
    import httpx

    from openatlas.net import client as net_client

    def _refuse(request):
        raise httpx.ConnectError("network disabled in tests", request=request)

    monkeypatch.setattr(net_client, "TRANSPORT", httpx.MockTransport(_refuse))
    real_send = httpx.Client.send

    # In-process transports never touch the network: mocks, and the ASGI app transport
    # that starlette's TestClient uses (not a MockTransport subclass since starlette 1.x).
    try:
        from starlette.testclient import _TestClientTransport
    except ImportError:  # pragma: no cover - web extra not installed
        _TestClientTransport = httpx.MockTransport
    offline = (httpx.MockTransport, _TestClientTransport)

    def _sync_send(self, request, *a, **k):
        if isinstance(getattr(self, "_transport", None), offline):
            return real_send(self, request, *a, **k)
        raise httpx.ConnectError("network disabled in tests", request=request)

    monkeypatch.setattr(httpx.Client, "send", _sync_send)

    # robots.txt lookups: default to "no robots.txt" (allow); robots tests override this.
    from openatlas.utils import robots

    monkeypatch.setattr(robots, "_fetch_text", lambda *a, **k: None)


@pytest.fixture
def mock_http(monkeypatch):
    """Install a fake web for the v2 net client: ``mock_http({url_prefix: response})``.

    A response may be a dict/list (JSON, 200), a str (HTML, 200), an (status, body) tuple,
    or a callable(request) -> httpx.Response. Unmatched URLs return 404.
    """
    import json as _json

    import httpx

    from openatlas.net import client as net_client

    def install(routes):
        def handler(request):
            url = str(request.url)
            for prefix in sorted(routes, key=len, reverse=True):
                if url.startswith(prefix):
                    spec = routes[prefix]
                    if callable(spec):
                        return spec(request)
                    status, body = spec if isinstance(spec, tuple) else (200, spec)
                    if isinstance(body, (dict, list)):
                        return httpx.Response(status, content=_json.dumps(body).encode(),
                                              headers={"content-type": "application/json"})
                    return httpx.Response(status, content=str(body).encode(),
                                          headers={"content-type": "text/html"})
            return httpx.Response(404, content=b"not found")

        monkeypatch.setattr(net_client, "TRANSPORT", httpx.MockTransport(handler))

    return install


@pytest.fixture(autouse=True)
def _isolated_robots_cache(tmp_path, monkeypatch):
    """Keep robots.txt snapshots written during tests out of the real data dir."""
    from openatlas.config import Config
    from openatlas.utils import robots

    monkeypatch.setattr(Config.files, "robots_cache", tmp_path / "robots_cache")
    robots._PARSER_CACHE.clear()
    yield


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the Ollama backend to appear unavailable unless a test opts in."""
    from openatlas.llm import ollama_client

    monkeypatch.setattr(ollama_client, "ping", lambda *a, **k: False)
    monkeypatch.setattr(ollama_client, "available", lambda *a, **k: False)
