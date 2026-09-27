"""Backward-compatible launcher: the Streamlit UI was replaced by ``openatlas serve``."""

from __future__ import annotations


def launch() -> int:
    from openatlas.web.server import serve

    return serve()
