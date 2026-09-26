"""OAtlas-style bookkeeping: the class_function_dict, derived from the live registry.

Upstream OAtlas keeps a hand-maintained ``class_function_dict`` mapping each engine
class to its function names. OpenAtlas derives it automatically from the registry so
it can never drift out of sync, while preserving the same public name.
"""

from __future__ import annotations

from typing import Dict, List

from openatlas.core.registry import ToolRegistry, load_all_engines


def class_function_dict() -> Dict[str, List[str]]:
    load_all_engines()
    return ToolRegistry.class_function_dict()
