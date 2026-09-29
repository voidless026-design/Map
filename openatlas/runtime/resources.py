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


# ---------------------------------------------------------------- display GPU (for the 3D brain)
# NVIDIA Kepler PCI device-ID ranges (GK107, GK110, GK104, GK106, GK208). nouveau doesn't
# reclock these by itself, so the card stays at its slowest boot clock (e.g. a GTX 770, 0x1184).
_KEPLER = ((0x0FC0, 0x0FFF), (0x1000, 0x103F), (0x1180, 0x11BF), (0x11C0, 0x11FF), (0x1280, 0x12BF))


def drm_gpus(root: str = "/sys/class/drm") -> List[Dict[str, Any]]:
    """Display GPUs from sysfs (Linux, no root): vendor/device IDs and the kernel driver in use."""
    out: List[Dict[str, Any]] = []
    try:
        cards = sorted(n for n in os.listdir(root) if n.startswith("card") and n[4:].isdigit())
    except OSError:
        return out
    for card in cards:
        dev = os.path.join(root, card, "device")
        try:
            with open(os.path.join(dev, "vendor")) as f:
                vendor = int(f.read().strip(), 16)
            with open(os.path.join(dev, "device")) as f:
                device = int(f.read().strip(), 16)
        except (OSError, ValueError):
            continue
        driver = os.path.basename(os.path.realpath(os.path.join(dev, "driver"))) if os.path.exists(os.path.join(dev, "driver")) else ""
        out.append({"card": card, "vendor": vendor, "device": device, "driver": driver,
                    "kepler": vendor == 0x10DE and any(a <= device <= b for a, b in _KEPLER)})
    return out


def brain3d_advice(root: str = "/sys/class/drm") -> Dict[str, Any]:
    """What limits the 3D brain on this PC's graphics, with copy-paste steps (empty issue = fine)."""
    gpus = drm_gpus(root)
    slow = next((g for g in gpus if g["vendor"] == 0x10DE and g["driver"] == "nouveau"), None)
    if not slow:
        return {"issue": "", "gpus": gpus}
    n = slow["card"][4:]
    steps = [f"sudo cat /sys/kernel/debug/dri/{n}/pstate",
             f"sudo sh -c 'echo 0f > /sys/kernel/debug/dri/{n}/pstate'",
             "Firefox: open about:support - if Compositing says 'WebRender (Software)', open about:config, "
             "set gfx.webrender.all to true and restart Firefox"]
    what = "a Kepler card (like the GTX 770)" if slow["kepler"] else "this NVIDIA card"
    msg = (f"The open 'nouveau' driver runs {what} at its slowest clock speed, so 3D is slow. "
           "Raise the clock (resets at reboot; pick the highest level the first command lists, usually 0f), "
           "and let Firefox composite on the GPU.")
    return {"issue": "nouveau", "kepler": slow["kepler"], "card": slow["card"], "message": msg, "steps": steps, "gpus": gpus}
