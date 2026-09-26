"""Core invariants: every engine registers, and methods.yaml matches the registry."""

from __future__ import annotations

from openatlas.core.registry import ToolRegistry, load_all_engines
from openatlas.utils.schema_validate import validate_methods_yaml


def test_engines_register():
    load_all_engines()
    cfd = ToolRegistry.class_function_dict()
    assert len(cfd) >= 18, "expected ~18 engines"
    total = sum(len(v) for v in cfd.values())
    assert total >= 40, "expected 40+ functions"


def test_methods_yaml_matches_registry():
    report = validate_methods_yaml()
    assert report["ok"], f"methods.yaml errors: {report['errors']}"


def test_every_function_has_spec_and_callable():
    load_all_engines()
    for name, engine in ToolRegistry.all_functions().items():
        assert name in engine.specs, f"{name} missing ToolSpec"
        assert callable(engine.get_callable(name)), f"{name} not callable"
