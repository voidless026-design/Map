"""Resource controls: profiles, memory guard, model cache, LLM gate, net client limits."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest

from openatlas.runtime import limits, profiles
from openatlas.runtime.resources import GPU, Hardware


@pytest.fixture(autouse=True)
def _fresh_profile(monkeypatch):
    for var in ("OPENATLAS_PROFILE", "OPENATLAS_LLM_MODEL", "OPENATLAS_VISION_MODEL"):
        monkeypatch.delenv(var, raising=False)
    profiles.reset()
    yield
    profiles.reset()


def test_profile_choice_by_hardware():
    assert profiles.choose(Hardware(16, 8, [GPU("nvidia", "RTX", 8.0)])) == "gpu"
    assert profiles.choose(Hardware(16, 8, [])) == "standard"
    assert profiles.choose(Hardware(8, 4, [])) == "lite"
    assert profiles.PROFILES["lite"].vision_model is None  # vision off on small machines


def test_profile_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENATLAS_PROFILE", "lite")
    monkeypatch.setenv("OPENATLAS_LLM_MODEL", "qwen2.5:3b")
    profiles.reset()
    p = profiles.active()
    assert p.name == "lite" and p.text_model == "qwen2.5:3b"


def test_memory_guard_refuses_when_ram_is_short(monkeypatch):
    monkeypatch.setattr(limits, "available_ram_gb", lambda: 4.0)
    ok, why = limits.memory_ok(5.6)
    assert not ok and "needs ~5.6 GB" in why
    ok, _ = limits.memory_ok(1.0)
    assert ok


def test_model_cache_loads_once():
    calls = []
    limits.drop_models()
    for _ in range(3):
        limits.cached_model("t:model", lambda: calls.append(1) or object())
    assert len(calls) == 1
    limits.drop_models()


def test_downscale_image(tmp_path):
    from PIL import Image

    big = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000), "white").save(big)
    small = limits.downscale_image(str(big), 1024)
    with Image.open(small) as im:
        assert max(im.size) == 1024


def _fake_ollama(monkeypatch, *, loaded=None, delay=0.05):
    """Pretend Ollama is up; record concurrency of /api/chat calls and unloads."""
    from openatlas.llm import ollama_client

    state = {"active": 0, "peak": 0, "chats": 0, "unloaded": []}
    lock = threading.Lock()

    def fake_req(method, url, json=None, **kw):
        if method == "GET":  # /api/tags: the models this fake Ollama has pulled
            return httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}, {"name": "llama3.2:3b"}]})
        if url.endswith("/api/generate") and json.get("keep_alive") == 0:
            state["unloaded"].append(json["model"])
            return httpx.Response(200, json={})
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(delay)
        with lock:
            state["active"] -= 1
            state["chats"] += 1
        return httpx.Response(200, json={"message": {"content": "ok"}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(ollama_client, "ping", lambda *a, **k: True)
    monkeypatch.setattr(ollama_client, "loaded_models", lambda: loaded or [])
    monkeypatch.setattr(ollama_client, "_req", fake_req)
    monkeypatch.setattr(limits, "available_ram_gb", lambda: 64.0)
    return state


def test_llm_gate_serialises_requests(monkeypatch):
    from openatlas.llm import ollama_client

    state = _fake_ollama(monkeypatch)
    threads = [threading.Thread(target=ollama_client.complete, args=("hi",)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["chats"] == 6
    assert state["peak"] == 1, "two local-LLM requests ran at the same time"


def test_switching_models_unloads_the_other(monkeypatch):
    from openatlas.llm import ollama_client

    state = _fake_ollama(monkeypatch, loaded=[{"name": "llava:7b"}, {"name": "nomic-embed-text"}])
    assert ollama_client.complete("hi", model="llama3.1:8b") == "ok"
    assert state["unloaded"] == ["llava:7b"]  # chat model evicted, embedding model kept


def test_memory_guard_blocks_llm_load(monkeypatch):
    from openatlas.llm import ollama_client

    state = _fake_ollama(monkeypatch)
    monkeypatch.setattr(limits, "available_ram_gb", lambda: 2.0)
    monkeypatch.setattr(limits, "gpu_available", lambda: False)
    assert ollama_client.complete("hi", model="llama3.1:8b") is None
    assert state["chats"] == 0


# --------------------------------------------------------------------------- #
# net client
# --------------------------------------------------------------------------- #
def test_net_concurrency_is_bounded(monkeypatch):
    from openatlas.net import client

    async def handler(request):
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(client, "TRANSPORT", httpx.MockTransport(handler))

    async def go():
        async with client.Net(concurrency=5, per_host=2) as net:
            urls = [f"https://h{i % 3}.example/{i}" for i in range(40)]
            rs = await asyncio.gather(*(net.get(u) for u in urls))
            return net.peak_in_flight, rs

    peak, rs = asyncio.run(go())
    assert all(r.ok for r in rs)
    assert peak <= 5


def test_net_body_cap_and_credential_stripping(monkeypatch):
    from openatlas.net import client

    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"x" * 5000)

    monkeypatch.setattr(client, "TRANSPORT", httpx.MockTransport(handler))

    async def go():
        async with client.Net() as net:
            return await net.get("https://a.example/", max_bytes=1000,
                                 headers={"Authorization": "Bearer secret"})

    r = asyncio.run(go())
    assert r.truncated and len(r.content) == 1000
    assert seen["auth"] is None


def test_net_page_policy(monkeypatch):
    from openatlas.net import client
    from openatlas.utils import robots

    robots._PARSER_CACHE.clear()
    monkeypatch.setattr(robots, "_fetch_text", lambda *a, **k: "User-agent: *\nDisallow: /private")

    async def go():
        async with client.Net() as net:
            broker = await net.get("https://www.spokeo.com/Jane-Doe", page=True)
            blocked = await net.get("https://site.example/private/x", page=True)
            return broker, blocked

    broker, blocked = asyncio.run(go())
    assert "data-broker" in broker.error
    assert "robots.txt" in blocked.error
