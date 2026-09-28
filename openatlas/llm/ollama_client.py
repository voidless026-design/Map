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
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import httpx

from openatlas.config import Config
from openatlas.logger import get_logger
from openatlas.runtime import limits, profiles

log = get_logger("openatlas.llm")

KEEP_ALIVE = os.getenv("OPENATLAS_LLM_KEEP_ALIVE", "2m")
TRANSPORT: Optional[httpx.BaseTransport] = None  # tests put a fake Ollama here


def _req(method: str, url: str, **kw: Any) -> httpx.Response:
    timeout = kw.pop("timeout", 30)
    with httpx.Client(transport=TRANSPORT, timeout=timeout) as c:
        return c.request(method, url, **kw)


def _url(path: str) -> str:
    return Config.llm.host.rstrip("/") + path


def ping(timeout: float = 2.0) -> bool:
    """Return True iff a local Ollama server is reachable."""
    try:
        return _req("GET", _url("/api/tags"), timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def available() -> bool:
    """True when a local Ollama server is reachable."""
    return ping()


def text_model() -> str:
    """The chat model to use: the profile's choice if it is installed, otherwise the closest
    installed one (so a missing ``llama3.1:8b`` never turns into a 404)."""
    return resolve_model(profiles.active().text_model) or profiles.active().text_model


# --------------------------------------------------------------------------- #
# which models are actually installed (the cause of "HTTP 404": model not pulled)
# --------------------------------------------------------------------------- #
_TAGS: Tuple[float, List[str]] = (0.0, [])
_TAGS_TTL = 60.0
_NON_CHAT = ("embed", "minilm", "bge", "e5-", "llava", "moondream", "vision", "whisper", "clip")


def installed_models(refresh: bool = False) -> List[str]:
    """Names from ``/api/tags`` (cached for a minute); [] when Ollama isn't reachable."""
    global _TAGS
    if not refresh and _TAGS[1] and time.monotonic() - _TAGS[0] < _TAGS_TTL:
        return list(_TAGS[1])
    try:
        resp = _req("GET", _url("/api/tags"), timeout=3)
        names = [m.get("name") or m.get("model") or "" for m in resp.json().get("models", [])] \
            if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        names = []
    _TAGS = (time.monotonic(), [n for n in names if n])
    return list(_TAGS[1])


def _family(name: str) -> str:
    return name.split(":", 1)[0]


def _size_hint(name: str) -> float:
    """'llama3.1:8b' -> 8.0 (used to prefer the most capable installed model)."""
    tag = name.split(":", 1)[1] if ":" in name else ""
    num = "".join(ch for ch in tag.split("-")[0] if ch.isdigit() or ch == ".")
    try:
        return float(num)
    except ValueError:
        return 0.0


def resolve_model(preferred: str, *, chat_only: bool = True) -> Optional[str]:
    """The installed model to use instead of ``preferred``: an exact match, else the same family
    (``llama3.1:latest`` for ``llama3.1:8b``), else the biggest installed chat model up to
    ~14B. None when nothing suitable is installed (or Ollama is down)."""
    names = installed_models()
    if not names:
        return None
    norm = {n: n if ":" in n else n + ":latest" for n in names}
    want = preferred if ":" in preferred else preferred + ":latest"
    for n, full in norm.items():
        if full == want:
            return n
    same = [n for n in names if _family(n) == _family(preferred)]
    if same:
        return same[0]
    chat = [n for n in names if not (chat_only and any(k in n.lower() for k in _NON_CHAT))]
    if not chat:
        return None
    fits = [n for n in chat if _size_hint(n) <= 14] or chat
    return sorted(fits, key=_size_hint)[-1]


def diagnose(preferred: Optional[str] = None) -> Dict[str, Any]:
    """Why the local AI can or can't answer, in words a person can act on."""
    preferred = preferred or profiles.active().text_model
    if not ping():
        return {"ok": False, "reason": "not_running",
                "message": f"Ollama isn't running at {Config.llm.host}. Start it with: ollama serve"}
    names = installed_models(refresh=True)
    chosen = resolve_model(preferred)
    if not chosen:
        return {"ok": False, "reason": "no_model", "installed": names,
                "message": f"Ollama is running but has no chat model. Install one with: ollama pull {preferred}"}
    note = "" if chosen.split(":")[0] == preferred.split(":")[0] else \
        f" ({preferred} isn't installed; using {chosen}. For the best answers: ollama pull {preferred})"
    return {"ok": True, "reason": "ok", "model": chosen, "installed": names,
            "message": f"local AI ready: {chosen}{note}"}


def vision_model() -> Optional[str]:
    return profiles.active().vision_model


def loaded_models() -> List[Dict[str, Any]]:
    """Models currently resident in Ollama (``/api/ps``); [] if unreachable."""
    try:
        resp = _req("GET", _url("/api/ps"), timeout=3)
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
        _req("POST", _url("/api/generate"), json={"model": model, "keep_alive": 0}, timeout=10)
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
    model = resolve_model(model) or model if model else text_model()
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
            resp = _req("POST",
                _url("/api/chat"),
                json={"model": model, "messages": messages, "stream": False,
                      "keep_alive": KEEP_ALIVE, "options": options},
                timeout=timeout or Config.llm.request_timeout,
            )
            if resp.status_code == 404:
                log.warning("Ollama has no model %s - run: ollama pull %s", model, model)
                installed_models(refresh=True)
                return None
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Ollama chat failed: %s", exc)
            return None


class LLMUnavailable(RuntimeError):
    """The local model can't answer; ``str(exc)`` says what to do about it."""


def stream_chat(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    stop: Optional[Any] = None,
) -> Iterator[Dict[str, Any]]:
    """Stream a chat turn from local Ollama (native ``/api/chat``).

    Yields ``{"type": "token", "text": ...}`` as text arrives, ``{"type": "tool_calls",
    "calls": [...]}`` when the model asks for tools, and a final ``{"type": "done", ...}``.
    Raises :class:`LLMUnavailable` with an actionable message (not running / no model /
    out of memory). ``stop`` (a threading.Event) cancels mid-stream, e.g. on barge-in."""
    diag = diagnose(model) if model else diagnose()
    if not diag["ok"]:
        raise LLMUnavailable(diag["message"])
    use = diag["model"] if not model else (resolve_model(model) or diag["model"])
    prof = profiles.active()
    body: Dict[str, Any] = {
        "model": use, "messages": messages, "stream": True, "keep_alive": KEEP_ALIVE,
        "options": {"num_ctx": prof.num_ctx,
                    "temperature": Config.llm.temperature if temperature is None else temperature}}
    if tools:
        body["tools"] = tools
    t0 = time.monotonic()
    first = None
    with limits.LLM_GATE:
        problem = _prepare(use)
        if problem:
            raise LLMUnavailable(problem)
        try:
            with httpx.Client(transport=TRANSPORT, timeout=timeout or Config.llm.request_timeout) as c, \
                    c.stream("POST", _url("/api/chat"), json=body) as resp:
                if resp.status_code == 404:
                    installed_models(refresh=True)
                    raise LLMUnavailable(f"Ollama has no model {use}. Install it with: ollama pull {use}")
                if resp.status_code == 400 and tools:
                    raise LLMUnavailable(f"tools_unsupported:{use}")
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if stop is not None and stop.is_set():
                        yield {"type": "done", "model": use, "cancelled": True,
                               "first_token_ms": first}
                        return
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    msg = chunk.get("message") or {}
                    if msg.get("tool_calls"):
                        yield {"type": "tool_calls", "calls": msg["tool_calls"]}
                    if msg.get("content"):
                        if first is None:
                            first = round((time.monotonic() - t0) * 1000)
                        yield {"type": "token", "text": msg["content"]}
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Ollama stopped answering ({type(exc).__name__}). "
                                 "Is it still running? ollama serve") from exc
    yield {"type": "done", "model": use, "cancelled": False, "first_token_ms": first}


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
            resp = _req("POST", _url("/api/embed"),
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
        "model_in_use": resolve_model(prof.text_model),
        "installed": installed_models(),
        "vision_model": prof.vision_model,
        "embed_model": prof.embed_model,
        "num_ctx": prof.num_ctx,
        "keep_alive": KEEP_ALIVE,
    }
