"""Hardware detection: RAM, CPU and GPU (NVIDIA / AMD), without heavy dependencies.

GPU detection shells out to ``nvidia-smi`` / ``rocm-smi`` when present; absence of either
simply means "no GPU detected". Results are cached for the life of the process.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil is a core dependency
    psutil = None  # type: ignore[assignment]

GB = 1024**3


@dataclasses.dataclass
class GPU:
    vendor: str  # "nvidia" | "amd"
    name: str
    vram_gb: float


@dataclasses.dataclass
class Hardware:
    total_ram_gb: float
    cpu_count: int
    gpus: List[GPU]

    @property
    def max_vram_gb(self) -> float:
        return max((g.vram_gb for g in self.gpus), default=0.0)

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["available_ram_gb"] = available_ram_gb()
        d["max_vram_gb"] = self.max_vram_gb
        return d


def available_ram_gb() -> float:
    """Currently available RAM in GB (not cached - changes constantly)."""
    if psutil is not None:
        return round(psutil.virtual_memory().available / GB, 2)
    try:  # pragma: no cover - Linux fallback
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) * 1024 / GB, 2)
    except OSError:
        pass
    return 0.0


def _total_ram_gb() -> float:
    if psutil is not None:
        return round(psutil.virtual_memory().total / GB, 2)
    return 0.0  # pragma: no cover


def _run(cmd: List[str]) -> Optional[str]:
    if not shutil.which(cmd[0]):
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _nvidia_gpus() -> List[GPU]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    gpus: List[GPU] = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                gpus.append(GPU("nvidia", parts[0], round(float(parts[1]) / 1024, 1)))
            except ValueError:
                continue
    return gpus


def _amd_gpus() -> List[GPU]:
    out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    gpus: List[GPU] = []
    if not out:
        return gpus
    try:
        data = json.loads(out)
    except ValueError:
        return gpus
    for card in data.values() if isinstance(data, dict) else []:
        if not isinstance(card, dict):
            continue
        name = card.get("Card series") or card.get("Card model") or "AMD GPU"
        total = card.get("VRAM Total Memory (B)")
        try:
            vram = round(int(total) / GB, 1) if total else 0.0
        except (TypeError, ValueError):
            vram = 0.0
        gpus.append(GPU("amd", str(name), vram))
    return gpus


@lru_cache(maxsize=1)
def detect() -> Hardware:
    """Detect hardware once per process."""
    return Hardware(
        total_ram_gb=_total_ram_gb(),
        cpu_count=os.cpu_count() or 1,
        gpus=_nvidia_gpus() + _amd_gpus(),
    )


def process_rss_mb() -> float:
    """Resident memory of this process in MB (for diagnostics/tests)."""
    if psutil is None:  # pragma: no cover
        return 0.0
    return round(psutil.Process().memory_info().rss / (1024**2), 1)

