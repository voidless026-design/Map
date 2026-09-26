"""Local LLM client for Ollama (native API) with hard resource limits.

OpenAtlas never calls a paid LLM API. Everything goes to a *local* Ollama server.
This client exists to keep that local model from overloading the machine:

* **One request at a time** (``runtime.limits.LLM_GATE``).
* **One chat model resident at a time**: before switching models, other loaded chat
  models are unloaded (``keep_alive: 0``). Small embedding models may stay.
* **Short residency**: every call sends ``keep_alive`` (default 2 minutes) so a model
  does not sit in RAM/VRAM forever.
* **Bounded context**: ``num_ctx`` comes from the active profile.
* **Memory guard**: a model that is not already loaded is only loaded if there is room.
* **GPU check**: :func:`gpu_report` reads ``/api/ps`` to show whether a model actually
  runs on the GPU (``size_vram``) or silently fell back to the CPU.

If Ollama is not running, every function degrades gracefully (returns ``None``).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from openatlas.config import Config
from openatlas.logger import get_logger
from openatlas.runtime import limits, profiles

log = get_logger("openatlas.llm")

KEEP_ALIVE = os.getenv("OPENATLAS_LLM_KEEP_ALIVE", "2m")


def _url(path: str) -> str:
    return Config.llm.host.rstrip("/") + path


def ping(timeout: float = 2.0) -> bool:
    """Return True iff a local Ollama server is reachable."""
    try:
        return httpx.get(_url("/api/tags"), timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def available() -> bool:
    """True when a local Ollama server is reachable."""
    return ping()


def text_model() -> str:
    return profiles.active().text_model


def vision_model() -> Optional[str]:
    return profiles.active().vision_model


def loaded_models() -> List[Dict[str, Any]]:
    """Models currently resident in Ollama (``/api/ps``); [] if unreachable."""
    try:
        resp = httpx.get(_url("/api/ps"), timeout=3)
        return resp.json().get("models", []) if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


def gpu_report() -> Dict[str, Any]:
    """Which loaded models run on the GPU vs CPU (answers "is Ollama using my GPU?")."""
    out = []
    for m in loaded_models():
        size, vram = m.get("size") or 0, m.get("size_vram") or 0
        out.append({
            "model": m.get("name") or m.get("model"),
            "size_gb": round(size / 1024**3, 2),
            "vram_gb": round(vram / 1024**3, 2),
            "on_gpu": bool(vram) and vram >= size * 0.9,
            "partly_cpu": bool(vram) and vram < size * 0.9,
        })
    return {"reachable": ping(), "models": out}


def unload(model: str) -> None:
    try:
        httpx.post(_url("/api/generate"), json={"model": model, "keep_alive": 0}, timeout=10)
    except httpx.HTTPError:
        pass


def _is_embed(name: str) -> bool:
    return any(k in name for k in ("embed", "minilm", "bge", "e5"))


def _prepare(model: str) -> Optional[str]:
    """Ensure ``model`` can be loaded safely. Returns an error string, or None if OK."""
    resident = [m.get("name") or m.get("model") or "" for m in loaded_models()]
    if model in resident:
        return None
    # One chat model at a time: evict other chat models first.
    for other in resident:
        if other and other != model and not _is_embed(other):
            log.info("unloading %s before loading %s", other, model)
            unload(other)
    ok, reason = limits.memory_ok(limits.need_for(model), on_gpu=limits.gpu_available())
    if not ok:
        return f"refusing to load {model}: {reason}"
    return None


def chat(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """Run a chat completion on the local model. Returns text, or None if unavailable."""
    if not ping():
        log.debug("Ollama unavailable (%s) - degrading gracefully.", Config.llm.host)
        return None
    model = model or text_model()
    prof = profiles.active()
    options: Dict[str, Any] = {
        "num_ctx": prof.num_ctx,
        "temperature": Config.llm.temperature if temperature is None else temperature,
    }
    if max_tokens:
        options["num_predict"] = max_tokens
    with limits.LLM_GATE:
        problem = _prepare(model)
        if problem:
            log.warning(problem)
            return None
        try:
            resp = httpx.post(
                _url("/api/chat"),
                json={"model": model, "messages": messages, "stream": False,
                      "keep_alive": KEEP_ALIVE, "options": options},
                timeout=timeout or Config.llm.request_timeout,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Ollama chat failed: %s", exc)
            return None


def complete(prompt: str, *, system: Optional[str] = None, **kwargs: Any) -> Optional[str]:
    """Convenience single-prompt wrapper around :func:`chat`."""
    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, **kwargs)


def vision(prompt: str, image_path: str, *, model: Optional[str] = None,
           **kwargs: Any) -> Optional[str]:
    """Vision+text prompt on the local vision model (image downscaled first)."""
    model = model or vision_model()
    if not model:
        log.info("vision disabled in the '%s' profile", profiles.active().name)
        return None
    small = limits.downscale_image(image_path)
    try:
        b64 = base64.b64encode(Path(small).read_bytes()).decode("ascii")
    except OSError as exc:
        log.debug("cannot read image %s: %s", image_path, exc)
        return None
    return chat([{"role": "user", "content": prompt, "images": [b64]}], model=model, **kwargs)


def embed(texts: List[str], *, model: Optional[str] = None,
          timeout: float = 120) -> Optional[List[List[float]]]:
    """Embed texts with the local embedding model. None if unavailable."""
    if not texts or not ping():
        return None
    model = model or profiles.active().embed_model
    with limits.LLM_GATE:
        try:
            resp = httpx.post(_url("/api/embed"),
                              json={"model": model, "input": texts, "keep_alive": KEEP_ALIVE},
                              timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("embeddings")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Ollama embed failed: %s", exc)
            return None


def status() -> Dict[str, Any]:
    """LLM backend status for diagnostics and the GUI."""
    prof = profiles.active()
    return {
        "host": Config.llm.host,
        "reachable": ping(),
        "profile": prof.name,
        "text_model": prof.text_model,
        "vision_model": prof.vision_model,
        "embed_model": prof.embed_model,
        "num_ctx": prof.num_ctx,
        "keep_alive": KEEP_ALIVE,
    }
