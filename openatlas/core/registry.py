"""Tool registry and base classes for OpenAtlas engines.

This is a clean-room reimplementation of the registry/tool pattern popularised by
OpenJarvis (Apache-2.0): a ``@ToolRegistry.register("name")`` decorator over a
``BaseTool`` subclass that exposes a ``ToolSpec`` and an ``execute()`` returning a
``ToolResult``. See NOTICE for attribution.

Every OSINT function in OpenAtlas is a *method* grouped under an *engine* class
(mirroring OAtlas's ``class_function_dict`` layout), but each engine also registers
itself here so the CLI, the web UI, and the ``skill-forge`` verifier can discover
and introspect it uniformly.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Callable, Dict, List, Optional, Type


@dataclasses.dataclass
class ToolSpec:
    """Declarative description of a single callable function within an engine."""

    name: str
    description: str
    parameters: Dict[str, Dict[str, Any]] = dataclasses.field(default_factory=dict)
    category: str = "osint"
    # Free/local backend this call relies on (for --show-api-services & audits).
    backend: str = "local"
    # True when the call reaches out over the network to a public endpoint.
    network: bool = False
    # True when the call performs any web scraping (=> robots.txt is enforced).
    scrapes_web: bool = False
    # True when the call needs a live Ollama backend to be fully functional.
    needs_llm: bool = False
    timeout_seconds: int = 60
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ToolResult:
    """Uniform result envelope returned by every function.

    ``success`` is ``False`` for graceful degradation (e.g. the Ollama backend is
    unreachable) as well as hard errors; ``content`` always carries a
    JSON-serialisable payload so results can be logged to the database verbatim.
    """

    tool_name: str
    content: Any
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, indent=2)

    @classmethod
    def unavailable(cls, tool_name: str, reason: str, **meta: Any) -> "ToolResult":
        """Helper for 'backend not available' graceful degradation."""
        return cls(
            tool_name=tool_name,
            content={"result": None, "reason": reason},
            success=False,
            error=reason,
            metadata={"degraded": True, **meta},
        )

    @classmethod
    def failure(cls, tool_name: str, reason: str, **meta: Any) -> "ToolResult":
        return cls(
            tool_name=tool_name,
            content={"result": False, "reason": reason},
            success=False,
            error=reason,
            metadata=meta,
        )


class BaseTool:
    """Base class every engine inherits from.

    An engine bundles one or more related functions. Each public function is a
    ``@staticmethod`` (OAtlas convention) so it can be called directly without
    instantiating the engine, while the engine object itself carries the
    :pyattr:`specs` used for discovery and verification.
    """

    #: Human-friendly engine name, e.g. "email-verification".
    common_name: str = ""
    #: Abbreviated OAtlas-style handle, e.g. "ecE".
    abbrev: str = ""
    #: One-line engine description.
    description: str = ""
    #: Per-function ToolSpec objects, keyed by function name.
    specs: Dict[str, ToolSpec] = {}

    @classmethod
    def function_names(cls) -> List[str]:
        return sorted(cls.specs.keys())

    @classmethod
    def get_callable(cls, name: str) -> Optional[Callable[..., ToolResult]]:
        fn = getattr(cls, name, None)
        return fn if callable(fn) else None


class ToolRegistry:
    """Global registry of engine classes, keyed by common_name and by function."""

    _engines: Dict[str, Type[BaseTool]] = {}

    @classmethod
    def register(cls, common_name: str) -> Callable[[Type[BaseTool]], Type[BaseTool]]:
        def _decorator(engine: Type[BaseTool]) -> Type[BaseTool]:
            engine.common_name = common_name
            if common_name in cls._engines:
                raise ValueError(f"Engine '{common_name}' already registered")
            cls._engines[common_name] = engine
            return engine

        return _decorator

    # ---- discovery -------------------------------------------------------- #
    @classmethod
    def engines(cls) -> Dict[str, Type[BaseTool]]:
        return dict(cls._engines)

    @classmethod
    def all_functions(cls) -> Dict[str, Type[BaseTool]]:
        """Map every function name -> its owning engine class."""
        out: Dict[str, Type[BaseTool]] = {}
        for engine in cls._engines.values():
            for fname in engine.function_names():
                out[fname] = engine
        return out

    @classmethod
    def engine_for_function(cls, function_name: str) -> Optional[Type[BaseTool]]:
        return cls.all_functions().get(function_name)

    @classmethod
    def spec_for_function(cls, function_name: str) -> Optional[ToolSpec]:
        engine = cls.engine_for_function(function_name)
        if engine is None:
            return None
        return engine.specs.get(function_name)

    @classmethod
    def class_function_dict(cls) -> Dict[str, List[str]]:
        """OAtlas-style bookkeeping map: EngineClassName -> [function names]."""
        return {
            engine.__name__: engine.function_names() for engine in cls._engines.values()
        }

    @classmethod
    def clear(cls) -> None:  # pragma: no cover - test helper
        cls._engines.clear()


def load_all_engines() -> None:
    """Import the tools package so every engine registers itself.

    Kept as a function (not import-time side effect) so tests can control
    registration order and the registry can be cleared/reloaded.
    """
    import importlib

    importlib.import_module("openatlas.tools")
