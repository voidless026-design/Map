"""Run a coroutine from sync code, whether or not an event loop is already running."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, TypeVar

T = TypeVar("T")


def run_sync(coro: Awaitable[T]) -> T:
    """``asyncio.run`` that also works inside a running loop (runs in a helper thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    box: dict = {}

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(coro)  # type: ignore[arg-type]
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


def as_thread(fn: Any, *args: Any, **kwargs: Any) -> Awaitable[Any]:
    """Shorthand for ``asyncio.to_thread`` (blocking library calls inside async code)."""
    return asyncio.to_thread(fn, *args, **kwargs)
