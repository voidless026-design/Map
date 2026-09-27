"""Read your ZIM books inside Atlas: runs Kiwix's own reader (``kiwix-serve``) on loopback.

``kiwix-serve`` comes with Kiwix's free tools (Fedora: ``sudo dnf install kiwix-tools``). Atlas
starts it on 127.0.0.1 with ``--urlRootLocation /kiwix`` and proxies ``/kiwix/*`` through its own
web server, so the Library tab can show Kiwix inside the app (same origin, same access token).
Without the binary everything else still works; the tab shows the install hint.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from openatlas.kb import library
from openatlas.logger import get_logger

log = get_logger("openatlas.kiwix")

PORT = 8602
HINT = "Install Kiwix's reader to browse books here: sudo dnf install kiwix-tools"
_proc: Optional[subprocess.Popen] = None
_served: List[str] = []


def binary() -> Optional[str]:
    return shutil.which("kiwix-serve")


def books() -> List[str]:
    return [r["path"] for r in library.rows() if r["status"] in ("ready", "ingesting", "ingested")
            and Path(r["path"]).exists()]


def running() -> bool:
    return _proc is not None and _proc.poll() is None


def ensure(port: int = PORT) -> bool:
    """Start (or restart, when the set of books changed) kiwix-serve. False if unavailable."""
    global _proc, _served
    exe, files = binary(), books()
    if not exe or not files:
        return False
    if running() and files == _served:
        return True
    stop()
    cmd = [exe, "--address", "127.0.0.1", "--port", str(port), "--urlRootLocation", "/kiwix", *files]
    try:
        _proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _served = files
        log.info("kiwix-serve on 127.0.0.1:%s with %d book(s)", port, len(files))
        return True
    except OSError as exc:
        log.warning("kiwix-serve failed to start: %s", exc)
        return False


def stop() -> None:
    global _proc
    if running():
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def status() -> dict:
    return {"installed": bool(binary()), "running": running(), "books": len(books()),
            "url": "/kiwix/" if running() else None, "hint": None if binary() else HINT}
