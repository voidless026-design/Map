"""Version information for OpenAtlas."""

from functools import lru_cache

__version__ = "0.2.0"


@lru_cache(maxsize=1)
def version_info() -> str:
    """Return a human-readable version string."""
    return f"OpenAtlas v{__version__}"
