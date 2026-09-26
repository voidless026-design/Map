"""Ollama-backed LLM client (OpenAI-compatible), replacing OpenAI/VertexAI.

OpenAtlas never calls a paid LLM API. All reasoning, geolocation inference, browser
planning and search summarisation go through a *local* Ollama server via its
OpenAI-compatible ``/v1`` endpoint. If Ollama is not running (as in a CI container
with no GPU), every call degrades gracefully: :meth:`chat` returns ``None`` and the
caller emits a ``ToolResult.unavailable(...)`` instead of crashing.

Configure via env:
    OLLAMA_HOST            (default http://localhost:11434)
    OPENATLAS_LLM_MODEL    (default llama3.1:8b)
    OPENATLAS_VISION_MODEL (default llava:7b)
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from openatlas.config import Config
from openatlas.logger import get_logger

log = get_logger("openatlas.llm")


def ping(timeout: int = 3) -> bool:
    """Return True iff a local Ollama server is reachable."""
    url = Config.llm.host.rstrip("/") + "/api/tags"
    try:
        resp = requests.get(url, timeout=timeout)
        return resp.status_code == 200
    except requests.RequestException:
        return False


@lru_cache(maxsize=1)
def _client() -> Optional[Any]:
    """Lazily build an OpenAI client pointed at Ollama. None if lib missing."""
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover
        log.debug("openai client library unavailable: %s", exc)
        return None
    return OpenAI(base_url=Config.llm.base_url, api_key=Config.llm.api_key)


def available() -> bool:
    """True when both the client library and a live Ollama server are present."""
    return _client() is not None and ping()


def chat(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Optional[str]:
    """Run a chat completion against Ollama. Returns text, or None if unavailable."""
    client = _client()
    if client is None or not ping():
        log.debug("Ollama unavailable (%s) - degrading gracefully.", Config.llm.host)
        return None
    try:
        resp = client.chat.completions.create(
            model=model or Config.llm.text_model,
            messages=messages,
            temperature=Config.llm.temperature if temperature is None else temperature,
            max_tokens=max_tokens,
            timeout=Config.llm.request_timeout,
        )
        return resp.choices[0].message.content
    except Exception as exc:  # network / model-missing / etc.
        log.warning("Ollama chat failed: %s", exc)
        return None


def complete(prompt: str, *, system: Optional[str] = None, **kwargs: Any) -> Optional[str]:
    """Convenience single-prompt wrapper around :func:`chat`."""
    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, **kwargs)


def _encode_image(image_path: str) -> Optional[str]:
    try:
        data = Path(image_path).read_bytes()
    except OSError as exc:
        log.debug("cannot read image %s: %s", image_path, exc)
        return None
    return base64.b64encode(data).decode("ascii")


def vision(
    prompt: str, image_path: str, *, model: Optional[str] = None, **kwargs: Any
) -> Optional[str]:
    """Run a vision+text prompt against a local Ollama vision model.

    Returns text, or None if the backend/image is unavailable.
    """
    b64 = _encode_image(image_path)
    if b64 is None:
        return None
    if not (available()):
        return None
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    return chat(
        [{"role": "user", "content": content}],
        model=model or Config.llm.vision_model,
        **kwargs,
    )


def status() -> Dict[str, Any]:
    """Report LLM backend status for --show-api-services / diagnostics."""
    return {
        "host": Config.llm.host,
        "reachable": ping(),
        "text_model": Config.llm.text_model,
        "vision_model": Config.llm.vision_model,
        "client_lib": _client() is not None,
    }
