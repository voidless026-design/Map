"""Central logging for OpenAtlas, backed by rich when available."""

from __future__ import annotations

import logging
import os

try:
    from rich.logging import RichHandler

    _HAVE_RICH = True
except Exception:  # pragma: no cover - rich is a core dep but stay defensive
    _HAVE_RICH = False


def get_logger(name: str = "openatlas") -> logging.Logger:
    """Return a configured logger.

    The verbosity is controlled by the ``OPENATLAS_LOGLEVEL`` environment
    variable (default ``INFO``). The application also flips this to ``DEBUG``
    when the user passes ``-v/--verbose``.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = os.getenv("OPENATLAS_LOGLEVEL", "INFO").upper()
    logger.setLevel(level)

    if _HAVE_RICH:
        handler: logging.Handler = RichHandler(rich_tracebacks=True, show_path=False)
        fmt = "%(message)s"
    else:  # pragma: no cover
        handler = logging.StreamHandler()
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    handler.setFormatter(logging.Formatter(fmt))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def set_verbose(verbose: bool) -> None:
    """Flip the root openatlas logger between INFO and DEBUG."""
    logging.getLogger("openatlas").setLevel(logging.DEBUG if verbose else logging.INFO)


log = get_logger()
