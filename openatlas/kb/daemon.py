"""The always-on brain worker: ingest, then embed, forever (throttled).

Run it as a systemd user service (packaging/systemd/openatlas-brain.service) so the brain
keeps growing while the machine is on, or start it from the GUI (background thread).
"""

from __future__ import annotations

import asyncio
import signal
import threading
from typing import Optional

from openatlas.kb import embed, ingest, store
from openatlas.logger import get_logger

log = get_logger("openatlas.kb.daemon")


async def loop(stop: threading.Event, batch: int = 25) -> None:
    from openatlas.runtime import profiles

    while not stop.is_set():
        from openatlas.kb import library

        library.start_background()  # downloads + ZIM ingestion run in their own thread
        await ingest.run(max_tasks=batch, stop=stop)
        if profiles.active().name != "lite" and not store.get_meta("paused", False):
            try:
                await asyncio.to_thread(embed.embed_pending, 32)
            except Exception as exc:  # embeddings are optional
                log.debug("embedding skipped: %s", exc)
        if ingest.next_task() is None:
            await asyncio.sleep(30)


def main() -> int:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("brain daemon started (data: %s)", store.db_path())
    asyncio.run(loop(stop))
    store.set_meta("worker", {"state": "stopped", "at": store.now()})
    return 0


_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def start_background() -> bool:
    """Start the worker inside the current process (used by the GUI). False if running."""
    global _thread
    if _thread and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=lambda: asyncio.run(loop(_stop)), name="brain", daemon=True)
    _thread.start()
    return True


def stop_background() -> None:
    _stop.set()


def running_in_process() -> bool:
    return bool(_thread and _thread.is_alive())


if __name__ == "__main__":
    import sys

    sys.exit(main())
