"""Optional Streamlit web UI for OpenAtlas (a friendlier AA-mode front end).

Launched via ``python3 openatlas.py --start-web-server``. Requires the ``web`` group
(``poetry install --with web``). Everything it drives is the same free/local stack.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from openatlas.config import Config
from openatlas.logger import get_logger

log = get_logger("openatlas.web")


def launch() -> int:
    """Start the Streamlit server as a subprocess. Returns an exit code."""
    try:
        import streamlit  # noqa: F401
    except Exception:
        print("Streamlit is not installed. Run: poetry install --with web")
        return 1
    script = Path(__file__).with_name("_ui.py")
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(script),
        "--server.address", Config.web.host, "--server.port", str(Config.web.port),
    ]
    log.info("Starting web UI at http://%s:%s", Config.web.host, Config.web.port)
    return subprocess.call(cmd)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(launch())
