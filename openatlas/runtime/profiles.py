"""Resource profiles: which local models to use and how much work to run at once.

A profile is chosen automatically from the detected hardware and can be forced with
``OPENATLAS_PROFILE=lite|standard|gpu``. Individual models can still be overridden with
``OPENATLAS_LLM_MODEL`` / ``OPENATLAS_VISION_MODEL`` / ``OPENATLAS_EMBED_MODEL``.

``need_gb`` is the approximate memory a model needs once loaded (4-bit quantised, as
Ollama ships them). The memory guard uses it to refuse a load that would exhaust RAM
instead of letting the machine swap itself to death.
"""

from __future__ import annotations

import dataclasses
import os
from functools import lru_cache
from typing import Dict, Optional

from openatlas.runtime.resources import Hardware, detect


@dataclasses.dataclass(frozen=True)
class Profile:
    name: str
    text_model: str
    vision_model: Optional[str]  # None = vision features disabled
    embed_model: str
    num_ctx: int
    net_concurrency: int  # total simultaneous HTTP requests
    per_host: int  # simultaneous requests to one host
    ml_enabled: bool  # heavy local ML (transformers / DeepFace)
    summarize_search: bool  # LLM-summarise web search results by default
    ingest_rate: float  # knowledge-base requests per second

    def to_dict(self) -> Dict[str, object]:
        return dataclasses.asdict(self)


PROFILES: Dict[str, Profile] = {
    "lite": Profile(
        name="lite", text_model="llama3.2:3b", vision_model=None,
        embed_model="all-minilm", num_ctx=2048, net_concurrency=8, per_host=2,
        ml_enabled=False, summarize_search=False, ingest_rate=1.0,
    ),
    "standard": Profile(
        name="standard", text_model="llama3.2:3b", vision_model="moondream",
        embed_model="nomic-embed-text", num_ctx=4096, net_concurrency=16, per_host=4,
        ml_enabled=True, summarize_search=False, ingest_rate=2.0,
    ),
    "gpu": Profile(
        name="gpu", text_model="llama3.1:8b", vision_model="llava:7b",
        embed_model="nomic-embed-text", num_ctx=8192, net_concurrency=24, per_host=4,
        ml_enabled=True, summarize_search=True, ingest_rate=2.0,
    ),
}

# Approximate resident memory per model in GB (q4 quantisation, default context).
MODEL_NEED_GB: Dict[str, float] = {
    "llama3.2:1b": 1.3, "llama3.2:3b": 2.6, "qwen2.5:3b": 2.6, "llama3.1:8b": 5.6,
    "qwen2.5:7b": 5.4, "moondream": 1.7, "llava:7b": 5.6, "qwen2.5vl:7b": 6.0,
    "all-minilm": 0.1, "nomic-embed-text": 0.4,
}


def model_need_gb(model: str) -> float:
    """Best-effort memory need for a model tag (unknown tags assume 6 GB)."""
    return MODEL_NEED_GB.get(model, MODEL_NEED_GB.get(model.split(":")[0], 6.0))


def choose(hw: Hardware) -> str:
    """Pick a profile name for the given hardware."""
    if hw.max_vram_gb >= 6:
        return "gpu"
    if hw.total_ram_gb >= 15:
        return "standard"
    return "lite"


@lru_cache(maxsize=1)
def active() -> Profile:
    """The active profile (env override > hardware detection), with model overrides applied."""
    forced = os.getenv("OPENATLAS_PROFILE", "").strip().lower()
    base = PROFILES.get(forced) or PROFILES[choose(detect())]
    return dataclasses.replace(
        base,
        text_model=os.getenv("OPENATLAS_LLM_MODEL") or base.text_model,
        vision_model=os.getenv("OPENATLAS_VISION_MODEL") or base.vision_model,
        embed_model=os.getenv("OPENATLAS_EMBED_MODEL") or base.embed_model,
    )


def reset() -> None:
    """Forget the cached profile (tests / after changing env)."""
    active.cache_clear()
