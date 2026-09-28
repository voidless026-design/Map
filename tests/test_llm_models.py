"""The local model picker: a model that isn't pulled must never surface as "HTTP 404"."""

from __future__ import annotations

import pytest

from openatlas.llm import ollama_client


def test_exact_family_and_best_installed(fake_ollama):
    fake_ollama.models = ["llama3.1:8b", "nomic-embed-text:latest"]
    assert ollama_client.resolve_model("llama3.1:8b") == "llama3.1:8b"
    fake_ollama.models = ["llama3.1:latest"]
    ollama_client.installed_models(refresh=True)
    assert ollama_client.resolve_model("llama3.1:8b") == "llama3.1:latest"
    fake_ollama.models = ["qwen3:8b", "llama3.2:3b", "nomic-embed-text:latest", "llava:7b", "qwen2.5:72b"]
    ollama_client.installed_models(refresh=True)
    assert ollama_client.resolve_model("llama3.1:8b") == "qwen3:8b"  # biggest that fits, no embed/vision


def test_diagnose_explains_what_to_do(fake_ollama):
    fake_ollama.models = ["nomic-embed-text:latest"]
    d = ollama_client.diagnose("llama3.1:8b")
    assert not d["ok"] and d["reason"] == "no_model" and "ollama pull llama3.1:8b" in d["message"]
    fake_ollama.models = ["qwen3:8b"]
    d = ollama_client.diagnose("llama3.1:8b")
    assert d["ok"] and d["model"] == "qwen3:8b" and "ollama pull llama3.1:8b" in d["message"]


def test_diagnose_when_not_running():
    d = ollama_client.diagnose()
    assert d["reason"] == "not_running" and "ollama serve" in d["message"]


def test_chat_uses_an_installed_model_instead_of_404(fake_ollama):
    fake_ollama.models = ["qwen3:8b"]  # the profile wants llama3.1:8b, which isn't pulled
    fake_ollama.replies = ["Hello there"]
    assert ollama_client.chat([{"role": "user", "content": "hi"}]) == "Hello there"
    assert fake_ollama.requests[-1][1]["model"] == "qwen3:8b"


def test_stream_chat_tokens_tools_and_cancel(fake_ollama):
    import threading

    fake_ollama.replies = ["one two three", {"tool_calls": [{"function": {"name": "x", "arguments": {}}}]}]
    events = list(ollama_client.stream_chat([{"role": "user", "content": "hi"}]))
    assert "".join(e["text"] for e in events if e["type"] == "token") == "one two three"
    assert events[-1]["type"] == "done" and events[-1]["first_token_ms"] is not None
    events = list(ollama_client.stream_chat([{"role": "user", "content": "hi"}], tools=[{}]))
    assert events[0]["type"] == "tool_calls"
    stop = threading.Event()
    stop.set()
    fake_ollama.replies = ["a b c d"]
    events = list(ollama_client.stream_chat([{"role": "user", "content": "hi"}], stop=stop))
    assert events[-1]["cancelled"] is True


def test_stream_chat_raises_actionable_errors(fake_ollama):
    fake_ollama.models = []
    with pytest.raises(ollama_client.LLMUnavailable, match="ollama pull"):
        list(ollama_client.stream_chat([{"role": "user", "content": "hi"}]))


def test_visualizer_gets_an_installed_model(fake_ollama):
    from openatlas.utils import knowledge_graph

    fake_ollama.models = ["qwen3:8b"]
    assert knowledge_graph._llm_model() == "qwen3:8b"
