"""Tests for the knowledge-graph exporter that feeds the ATSMATRIX visualizer."""

from __future__ import annotations

import json

import pytest

from openatlas.core.database import db_funcs
from openatlas.core.registry import ToolResult
from openatlas.utils import knowledge_graph as kg


def _seed_session() -> str:
    sid = db_funcs.new_session("verify_email_address check_email_against_breach_data")
    ok = ToolResult(tool_name="verify_email_address",
                    content={"email": "jane@example.com", "has_mx": True, "valid_syntax": True})
    breach = ToolResult(tool_name="check_email_against_breach_data",
                        content={"email": "jane@example.com", "found": True,
                                 "breaches": [["Adobe", "LinkedIn"]]})
    degraded = ToolResult.unavailable("geolocate_using_LLMs", "Ollama unreachable")
    db_funcs.add_logs_to_database(sid, "verify_email_address", ok.to_dict(),
                                  engine_name="EmailCheckEngine", success=True)
    db_funcs.add_logs_to_database(sid, "check_email_against_breach_data", breach.to_dict(),
                                  engine_name="HaveIBeenPwnedEngine", success=True)
    db_funcs.add_logs_to_database(sid, "geolocate_using_LLMs", degraded.to_dict(),
                                  engine_name="ImageGeolocationEngine", success=False)
    return sid


def test_graph_schema_and_clusters():
    sid = _seed_session()
    g = kg.build_graph(sid)

    assert g["meta"]["session_id"] == sid
    assert g["clusters"] == kg.CLUSTERS
    ids = [n["id"] for n in g["nodes"]]
    assert len(ids) == len(set(ids)), "node ids must be unique"
    assert all(n["cluster"] in kg.CLUSTERS for n in g["nodes"])
    # every edge references existing nodes
    idset = set(ids)
    assert all(e["from"] in idset and e["to"] in idset for e in g["edges"])
    # target + report + one function node per run
    kinds = [n["kind"] for n in g["nodes"]]
    assert kinds.count("target") == 1 and kinds.count("report") == 1
    assert kinds.count("function") == 3
    # every finding names its parent run (the visualizer fans findings around it)
    runs = {n["id"] for n in g["nodes"] if n["kind"] == "function"}
    findings = [n for n in g["nodes"] if n["kind"] == "finding"]
    assert findings and all(f["parent"] in runs for f in findings)
    # events use the visualizer's 5 pipeline phases
    assert all(1 <= ev["phase"] <= 5 for ev in g["events"])
    json.dumps(g)  # serialisable


def test_engine_to_cluster_and_status():
    g = kg.build_graph(_seed_session())
    fn = {n["label"]: n for n in g["nodes"] if n["kind"] == "function"}
    assert fn["verify_email_address"]["cluster"] == "DISCOVERY"
    assert fn["check_email_against_breach_data"]["cluster"] == "VERIFICATION"
    assert fn["geolocate_using_LLMs"]["cluster"] == "REASONING"
    assert fn["geolocate_using_LLMs"]["status"] == "degraded"
    assert fn["verify_email_address"]["status"] == "ok"


def test_cross_link_on_shared_value_only():
    g = kg.build_graph(_seed_session())
    cross = [e for e in g["edges"] if e["kind"] == "cross-link"]
    # the same email surfaced by two runs -> exactly one cross-link;
    # the shared boolean flags must NOT create spurious links.
    assert len(cross) == 1
    assert any(ev["tag"] == "CROSS-LINK" for ev in g["events"])


def test_latest_session_default():
    _seed_session()
    newest = _seed_session()
    assert kg.build_graph()["meta"]["session_id"] == newest


def test_missing_session_raises():
    with pytest.raises(LookupError):
        kg.build_graph("does-not-exist")


def test_write_bundle(tmp_path):
    out = kg.write_bundle(kg.build_graph(_seed_session()), tmp_path / "viz")
    js = (out / "knowledge_graph.js").read_text()
    assert js.startswith("window.ATLAS_GRAPH = ")
    assert (out / "knowledge_graph.json").exists()
    html = (out / "index.html").read_text()
    assert '<script src="knowledge_graph.js"></script>' in html
    assert (out / "LICENSE.ATSMATRIX").exists()


def test_inline_html_escapes_script_close():
    g = kg.build_graph(_seed_session())
    g["meta"]["target"] = "</script><script>alert(1)</script>"
    html = kg.inline_html(g)
    assert "window.ATLAS_GRAPH" in html
    assert "</script><script>alert(1)" not in html


def test_visualizer_has_no_cloud_llm_or_keys():
    html = kg.VISUALIZER_HTML.read_text().lower()
    for bad in ("gemini", "generativelanguage", "api-key", "ats_gemini"):
        assert bad not in html, f"visualizer still references {bad!r}"


def test_cli_visualize_no_serve(tmp_path, monkeypatch):
    from openatlas.config import Config
    from openatlas.main import main

    sid = _seed_session()
    monkeypatch.setattr(Config.files, "output_dir", tmp_path)
    assert main(["--visualize", sid, "--viz-no-serve"]) == 0
    assert (tmp_path / "visualizer" / "knowledge_graph.js").exists()
