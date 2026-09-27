"""Hard limits that keep heavy work from overloading the machine.

* :data:`LLM_GATE` - one local-LLM request at a time, process-wide.
* :func:`memory_ok` - refuse to load a model when free memory is too low.
* :func:`cached_model` - load heavy ML models once and reuse them (they were previously
  re-loaded on every call, which is what exhausted RAM).
* :func:`downscale_image` - cap image size before any ML/vision inference.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from openatlas.logger import get_logger
from openatlas.runtime.resources import available_ram_gb, detect

log = get_logger("openatlas.limits")

#: Serialises every local-LLM call. Re-entrant so a helper can call another helper.
LLM_GATE = threading.RLock()

_MODEL_CACHE: Dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()

# Keep this much RAM free for the OS and the user's other programs.
HEADROOM_GB = 1.5


def memory_ok(need_gb: float, *, on_gpu: bool = False) -> Tuple[bool, str]:
    """Return (ok, reason). GPU loads are checked against VRAM, CPU loads against RAM."""
    if on_gpu:
        vram = detect().max_vram_gb
        if vram and need_gb <= vram * 0.95:
            return True, f"fits in {vram} GB VRAM"
        # Ollama will spill to system RAM - fall through and check RAM too.
    free = available_ram_gb()
    if free and free - need_gb < HEADROOM_GB:
        return False, (f"needs ~{need_gb} GB but only {free} GB RAM is free "
                       f"(keeping {HEADROOM_GB} GB headroom)")
    return True, f"{free} GB RAM free"


def cached_model(key: str, loader: Callable[[], Any]) -> Any:
    """Return a cached heavy model, loading it once (thread-safe)."""
    with _MODEL_LOCK:
        if key not in _MODEL_CACHE:
            log.info("loading model %s (once)", key)
            _MODEL_CACHE[key] = loader()
        return _MODEL_CACHE[key]


def drop_models() -> None:
    """Release every cached ML model (e.g. before loading a big LLM)."""
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()


def cached_model_keys() -> list:
    return sorted(_MODEL_CACHE)


def downscale_image(path: str, max_side: int = 1024) -> str:
    """Return a path to a copy of ``path`` no larger than ``max_side`` px (or the original)."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            if max(img.size) <= max_side:
                return path
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            out = Path(path).with_suffix(".oa-small.jpg")
            img.save(out, "JPEG", quality=88)
            return str(out)
    except Exception:  # unreadable image: let the caller report it
        return path


def need_for(model: str) -> float:
    from openatlas.runtime.profiles import model_need_gb

    return model_need_gb(model)


def gpu_available() -> bool:
    return detect().max_vram_gb > 0


def describe() -> Dict[str, Optional[object]]:
    return {"cached_models": cached_model_keys(), "headroom_gb": HEADROOM_GB}
