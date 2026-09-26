"""Runtime resource management: hardware detection, model profiles and hard limits.

This package exists to keep OpenAtlas from overloading the machine it runs on. Every
heavy thing (local LLMs, ML models, network fan-out, background ingestion) is sized by
the active profile and passes through the gates in :mod:`openatlas.runtime.limits`.
"""
