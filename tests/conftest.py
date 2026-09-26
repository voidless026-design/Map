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
