"""Validation helpers used by the CLI and by the ``skill-forge`` verifier.

Two layers:
* :func:`validate_methods_yaml` - lints ``methods/methods.yaml`` so every function
  declares a description and typed, documented arguments, and cross-checks it against
  the live registry (every registered function must be documented and vice-versa).
* :func:`validate_tool_result` - asserts that an object is a well-formed
  :class:`~openatlas.core.registry.ToolResult` (used in dry-runs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from openatlas.config import Config
from openatlas.core.registry import ToolRegistry, ToolResult, load_all_engines

_VALID_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


def _load_yaml(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path or Config.files.methods_yaml)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def validate_methods_yaml(
    path: Optional[str] = None, *, check_registry: bool = True
) -> Dict[str, Any]:
    """Return ``{"ok": bool, "errors": [...], "warnings": [...]}`` for methods.yaml."""
    errors: List[str] = []
    warnings: List[str] = []
    data = _load_yaml(path)

    if not data:
        return {"ok": False, "errors": ["methods.yaml is empty or missing"], "warnings": []}

    documented: set[str] = set()
    for engine_name, engine in data.items():
        if not isinstance(engine, dict):
            errors.append(f"{engine_name}: engine block must be a mapping")
            continue
        if "functions" not in engine or not isinstance(engine["functions"], dict):
            errors.append(f"{engine_name}: missing 'functions' mapping")
            continue
        for fname, fdef in engine["functions"].items():
            documented.add(fname)
            if not isinstance(fdef, dict):
                errors.append(f"{engine_name}.{fname}: definition must be a mapping")
                continue
            if not fdef.get("description"):
                errors.append(f"{engine_name}.{fname}: missing description")
            args = fdef.get("arguments", {}) or {}
            if not isinstance(args, dict):
                errors.append(f"{engine_name}.{fname}: 'arguments' must be a mapping")
                continue
            for arg_name, arg in args.items():
                if not isinstance(arg, dict):
                    errors.append(f"{engine_name}.{fname}.{arg_name}: arg must be a mapping")
                    continue
                atype = arg.get("type")
                if atype not in _VALID_TYPES:
                    errors.append(
                        f"{engine_name}.{fname}.{arg_name}: type '{atype}' "
                        f"not in {sorted(_VALID_TYPES)}"
                    )
                if "required" not in arg:
                    warnings.append(f"{engine_name}.{fname}.{arg_name}: no 'required' flag")
                if not arg.get("description"):
                    warnings.append(f"{engine_name}.{fname}.{arg_name}: no description")

    if check_registry:
        load_all_engines()
        registered = set(ToolRegistry.all_functions().keys())
        missing_docs = registered - documented
        missing_impl = documented - registered
        for fn in sorted(missing_docs):
            errors.append(f"function '{fn}' is registered but not documented in methods.yaml")
        for fn in sorted(missing_impl):
            warnings.append(f"function '{fn}' is documented but not registered")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def validate_tool_result(obj: Any) -> Dict[str, Any]:
    """Validate that ``obj`` is a well-formed ToolResult. Returns a report dict."""
    errors: List[str] = []
    if not isinstance(obj, ToolResult):
        return {"ok": False, "errors": [f"not a ToolResult (got {type(obj).__name__})"]}
    if not obj.tool_name:
        errors.append("tool_name is empty")
    if not isinstance(obj.success, bool):
        errors.append("success must be a bool")
    try:
        obj.to_json()
    except (TypeError, ValueError) as exc:
        errors.append(f"content is not JSON-serialisable: {exc}")
    if not obj.success and not obj.error:
        errors.append("failed result must carry an 'error' string")
    return {"ok": not errors, "errors": errors}
