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
def _isolated_brain(tmp_path, monkeypatch):
    """Cases persisted by pipeline tests go to a temp brain, never the real data dir."""
    from openatlas.config import Config
    from openatlas.kb import store

    monkeypatch.setattr(Config.files, "brain_dir", tmp_path / "brain")
    store.reset_init_cache()
    yield
    store.reset_init_cache()


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Force the Ollama backend to appear unavailable unless a test opts in."""
    from openatlas.llm import ollama_client

    monkeypatch.setattr(ollama_client, "ping", lambda *a, **k: False)
    monkeypatch.setattr(ollama_client, "available", lambda *a, **k: False)
    monkeypatch.setattr(ollama_client, "_TAGS", (0.0, []))


class FakeOllama:
    """A local Ollama stand-in: /api/tags, /api/ps, streaming /api/chat (NDJSON).

    ``replies`` is a queue; each item is a string (streamed as a few tokens) or
    ``{"tool_calls": [...]}``. Unknown models get 404, exactly like the real server."""

    def __init__(self, models=("llama3.1:8b",), replies=None, tools_ok=True):
        self.models, self.replies, self.tools_ok = list(models), list(replies or []), tools_ok
        self.requests = []

    def __call__(self, req):
        import json as _json

        import httpx

        path = req.url.path
        body = _json.loads(req.content or b"{}") if req.method == "POST" else {}
        self.requests.append((path, body))
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if path == "/api/chat":
            if body.get("model") not in self.models:
                return httpx.Response(404, json={"error": f"model '{body.get('model')}' not found"})
            if body.get("tools") and not self.tools_ok:
                return httpx.Response(400, json={"error": "does not support tools"})
            reply = self.replies.pop(0) if self.replies else "G'day! How can I help?"
            if isinstance(reply, dict):
                lines = [{"message": {"role": "assistant", "content": "", **reply}, "done": False}]
            else:
                words = reply.split(" ")
                lines = [{"message": {"role": "assistant", "content": w + (" " if i < len(words) - 1 else "")},
                          "done": False} for i, w in enumerate(words)]
            lines.append({"message": {"role": "assistant", "content": ""}, "done": True})
            if not body.get("stream", True):
                text = "" if isinstance(reply, dict) else reply
                return httpx.Response(200, json={"message": {"role": "assistant", "content": text,
                                                             **(reply if isinstance(reply, dict) else {})}})
            return httpx.Response(200, content="\n".join(_json.dumps(x) for x in lines).encode())
        if path == "/api/generate":
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def fake_ollama(monkeypatch):
    """Opt in to a running local Ollama (fake). Adjust ``.models`` / ``.replies`` in the test."""
    import httpx

    from openatlas.llm import ollama_client
    from openatlas.runtime import limits

    fake = FakeOllama()
    monkeypatch.setattr(ollama_client, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(ollama_client, "ping", lambda *a, **k: True)
    monkeypatch.setattr(ollama_client, "available", lambda *a, **k: True)
    monkeypatch.setattr(limits, "memory_ok", lambda *a, **k: (True, ""))
    return fake
