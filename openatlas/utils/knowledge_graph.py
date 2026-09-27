"""Export an OpenAtlas investigation session as a knowledge graph for the visualizer.

Reads a session's function runs from the database and emits the JSON graph consumed by
the forked ATSMATRIX visualizer (``openatlas/webserver/visualizer/atsmatrix.html``):

* **clusters** - the visualizer's four fixed clusters. Each run is placed by engine:
  collection engines -> DISCOVERY, LLM/search/browser/vision -> REASONING,
  breach / AI-image checks -> VERIFICATION, the aggregate report -> SYNTHESIS.
* **nodes** - the investigation target, one node per function run, a few extracted
  findings per run, and a report node.
* **edges** - target -> run, run -> finding, run -> report, plus *cross-links* between
  runs that surfaced the same value (e.g. the same email found by two engines).
* **events** - the recorded pipeline, tagged with the visualizer's 5 phases
  (1 COLLECT, 2 MATCH, 3 CROSS-LINK, 4 VERIFY, 5 SYNTH) and replayed in its HUD.

Everything is local: the bundle is static files served from 127.0.0.1, and the page's
chat talks only to a local Ollama. No network egress, no API keys.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openatlas.config import Config
from openatlas.core.database import db_funcs
from openatlas.runtime import profiles

CLUSTERS = ["DISCOVERY", "VERIFICATION", "REASONING", "SYNTHESIS"]

# Engine class name -> visualizer cluster.
CLUSTER_FOR_ENGINE: Dict[str, str] = {
    # Collection / discovery
    "EmailCheckEngine": "DISCOVERY",
    "RedditKnownEngine": "DISCOVERY",
    "RedditUnknownEngine": "DISCOVERY",
    "InstagramEngine": "DISCOVERY",
    "IPinfoEngine": "DISCOVERY",
    "UsernameCheckEngine": "DISCOVERY",
    "GitHubEngine": "DISCOVERY",
    "GetPagesEngine": "DISCOVERY",
    "HyperlinkExtractEngine": "DISCOVERY",
    "ProfessionalEmailFinderEngine": "DISCOVERY",
    "StaticImageExtractionEngine": "DISCOVERY",
    "NettackerEngine": "DISCOVERY",
    # Reasoning (LLM / search / browser / vision inference)
    "ImageGeolocationEngine": "REASONING",
    "PerplexityEngine": "REASONING",
    "BrowserAutomationEngine": "REASONING",
    "DeepScanEngine": "REASONING",
    # Verification
    "HaveIBeenPwnedEngine": "VERIFICATION",
    "OathNetEngine": "VERIFICATION",
    "VerifyAIGeneratedImageEngine": "VERIFICATION",
}

# Pipeline phase per cluster (visualizer HUD: 1 COLLECT .. 5 SYNTH).
PHASE_FOR_CLUSTER = {"DISCOVERY": 1, "REASONING": 3, "VERIFICATION": 4, "SYNTHESIS": 5}
PHASE_MATCH = 2

_MAX_FINDINGS_PER_RUN = 8
_LABEL_MAX = 60
# Keys that carry no investigative value as standalone findings.
_NOISE_KEYS = {"result", "reason", "note", "truncated", "text", "raw_description"}


def _short(value: Any, n: int = _LABEL_MAX) -> str:
    s = str(value).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse_output(raw: Any) -> Dict[str, Any]:
    """Runs store a ToolResult dict as JSON; tolerate raw values too."""
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {"content": raw}
    return data if isinstance(data, dict) and "content" in data else {"content": data}


def _status(run: Dict[str, Any], out: Dict[str, Any]) -> str:
    if run.get("success") and out.get("success", True):
        return "ok"
    meta = out.get("metadata") or {}
    return "degraded" if meta.get("degraded") else "failed"


def _findings(content: Any) -> List[Tuple[str, str]]:
    """Extract (label, value-key) pairs from a run's content. value-key drives cross-links."""
    found: List[Tuple[str, str]] = []

    def link_key(value: Any) -> str:
        # Only distinctive values may cross-link runs; booleans/tiny tokens would
        # falsely connect unrelated runs (e.g. two different `...: True` flags).
        if isinstance(value, bool):
            return ""
        s = str(value).strip().lower()
        if len(s) < 4 or s in {"true", "false", "none", "null"} or (s.isdigit() and len(s) < 6):
            return ""
        return s

    def add(label: str, value: Any) -> None:
        if len(found) < _MAX_FINDINGS_PER_RUN and value not in (None, "", [], {}):
            found.append((_short(label), link_key(value)))

    if isinstance(content, dict):
        for k, v in content.items():
            if k in _NOISE_KEYS:
                continue
            if isinstance(v, (str, int, float, bool)):
                add(f"{k}: {v}", v)
            elif isinstance(v, list):
                for item in v[:_MAX_FINDINGS_PER_RUN]:
                    if isinstance(item, (str, int, float)):
                        add(f"{k}: {item}", item)
                    elif isinstance(item, list):  # e.g. breaches: [["Adobe", ...]]
                        for sub in item[:_MAX_FINDINGS_PER_RUN]:
                            add(f"{k}: {sub}", sub)
            elif isinstance(v, dict):
                for sk, sv in list(v.items())[:_MAX_FINDINGS_PER_RUN]:
                    if isinstance(sv, (str, int, float, bool)):
                        add(f"{sk}: {sv}", sv)
    elif isinstance(content, list):
        for item in content[:_MAX_FINDINGS_PER_RUN]:
            add(item, item)
    elif content not in (None, ""):
        add(content, content)
    return found


def build_graph(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Build the visualizer graph for ``session_id`` (default: the latest session)."""
    sid = session_id or db_funcs.latest_session_id()
    if sid is None:
        raise LookupError("no investigation sessions found - run some functions first")
    session = db_funcs.get_session(sid)
    if session is None:
        raise LookupError(f"session '{sid}' not found")
    runs = db_funcs.get_runs(sid)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

    target_label = session.get("label") or sid
    nodes.append({"id": "target", "kind": "target", "cluster": "DISCOVERY",
                  "label": _short(f"target: {target_label}"), "status": "ok"})
    report_id = "report"

    value_owners: Dict[str, List[str]] = {}  # finding value -> finding node ids
    for i, run in enumerate(runs):
        out = _parse_output(run.get("output"))
        cluster = CLUSTER_FOR_ENGINE.get(run.get("engine_name", ""), "DISCOVERY")
        status = _status(run, out)
        run_id = f"run_{i}"
        detail = out.get("error") or ""
        nodes.append({"id": run_id, "kind": "function", "cluster": cluster,
                      "label": run.get("function_name", "?"), "status": status,
                      "engine": run.get("engine_name", ""), "detail": _short(detail, 160)})
        edges.append({"from": "target", "to": run_id, "kind": "ran"})
        edges.append({"from": run_id, "to": report_id, "kind": "feeds"})
        events.append({
            "tag": {"ok": "RUN", "degraded": "DEGRADED", "failed": "FAILED"}[status],
            "msg": _short(f"{run.get('function_name')} [{run.get('engine_name')}] -> {status}", 90),
            "phase": PHASE_FOR_CLUSTER[cluster],
        })

        for j, (label, value_key) in enumerate(_findings(out.get("content"))):
            fid = f"{run_id}_f{j}"
            nodes.append({"id": fid, "kind": "finding", "cluster": cluster, "parent": run_id,
                          "label": label, "status": status if status != "ok" else None})
            edges.append({"from": run_id, "to": fid, "kind": "found"})
            if value_key:
                value_owners.setdefault(value_key, []).append(fid)

    # Cross-links: the same value surfaced by more than one run.
    for value_key, owners in value_owners.items():
        run_ids = {o.split("_f")[0] for o in owners}
        if len(run_ids) < 2:
            continue
        first = owners[0]
        for other in owners[1:]:
            if other.split("_f")[0] != first.split("_f")[0]:
                edges.append({"from": first, "to": other, "kind": "cross-link"})
        events.append({"tag": "CROSS-LINK",
                       "msg": _short(f"'{value_key}' corroborated by {len(run_ids)} runs", 90),
                       "phase": PHASE_MATCH})

    ok = sum(1 for n in nodes if n["kind"] == "function" and n["status"] == "ok")
    nodes.append({"id": report_id, "kind": "report", "cluster": "SYNTHESIS",
                  "label": f"report: {ok}/{len(runs)} runs ok", "status": "ok"})
    events.append({"tag": "SYNTH", "msg": f"report assembled from {len(runs)} run(s)",
                   "phase": PHASE_FOR_CLUSTER["SYNTHESIS"]})

    return {
        "meta": {
            "source": "OpenAtlas",
            "session_id": sid,
            "target": target_label,
            "created_at": session.get("created_at"),
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "ollama_host": Config.llm.host,
            "model": profiles.active().text_model,
        },
        "clusters": CLUSTERS,
        "nodes": nodes,
        "edges": edges,
        "events": events,
    }


# --------------------------------------------------------------------------- #
# Bundling / serving
# --------------------------------------------------------------------------- #
VISUALIZER_DIR = Path(__file__).resolve().parent.parent / "webserver" / "visualizer"
VISUALIZER_HTML = VISUALIZER_DIR / "atsmatrix.html"
_DATA_TAG = '<script src="knowledge_graph.js"></script>'


def _graph_js(graph: Dict[str, Any]) -> str:
    # ensure_ascii escapes U+2028/2029; "</" is escaped so the payload is also safe inline.
    payload = json.dumps(graph, default=str).replace("</", "<\\/")
    return f"window.ATLAS_GRAPH = {payload};\n"


def write_bundle(graph: Dict[str, Any], out_dir: Optional[Path] = None) -> Path:
    """Write index.html + knowledge_graph.{js,json} + license into ``out_dir``."""
    out = Path(out_dir or (Path(Config.files.output_dir) / "visualizer"))
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(VISUALIZER_HTML, out / "index.html")
    lic = VISUALIZER_DIR / "LICENSE.ATSMATRIX"
    if lic.exists():
        shutil.copyfile(lic, out / "LICENSE.ATSMATRIX")
    (out / "knowledge_graph.js").write_text(_graph_js(graph), encoding="utf-8")
    (out / "knowledge_graph.json").write_text(json.dumps(graph, indent=2, default=str),
                                              encoding="utf-8")
    return out


def inline_html(graph: Dict[str, Any]) -> str:
    """Return a single self-contained HTML string with the graph embedded (for Streamlit)."""
    html = VISUALIZER_HTML.read_text(encoding="utf-8")
    return html.replace(_DATA_TAG, f"<script>{_graph_js(graph)}</script>", 1)


def serve(directory: Path, port: int = 8765, open_browser: bool = True) -> None:
    """Serve ``directory`` on 127.0.0.1 until interrupted (local only)."""
    import functools
    import http.server
    import webbrowser

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"Knowledge graph at {url}  (Ctrl+C to stop)")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


# --------------------------------------------------------------------------- #
# v2 cases -> graph (investigation evidence, with verification status)
# --------------------------------------------------------------------------- #
_CASE_CLUSTER = {"page-reader": "REASONING", "breaches": "VERIFICATION"}
_STATUS = {"confirmed": "verified", "refuted": "failed", "unverified": None}


def build_graph_from_case(report: Dict[str, Any]) -> Dict[str, Any]:
    """Visualizer graph for a v2 investigation case report."""
    t = report.get("target", {})
    nodes: List[Dict[str, Any]] = [{"id": "target", "kind": "target", "cluster": "DISCOVERY",
                                    "label": _short(f"target: {t.get('value')}"), "status": "ok"}]
    edges: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for ev in report.get("evidence", []):
        by_source.setdefault(ev["source"], []).append(ev)
    searched = {r["source"]: r for r in report.get("searched", [])}
    for src in sorted(set(by_source) | set(searched)):
        cluster = _CASE_CLUSTER.get(src, "DISCOVERY")
        res = searched.get(src, {"ok": True, "found": len(by_source.get(src, []))})
        sid = f"src_{src}"
        nodes.append({"id": sid, "kind": "function", "cluster": cluster, "label": src,
                      "status": "ok" if res.get("ok") else "failed",
                      "detail": _short(res.get("error") or res.get("searched") or "", 160)})
        edges.append({"from": "target", "to": sid, "kind": "ran"})
        edges.append({"from": sid, "to": "report", "kind": "feeds"})
        events.append({"tag": "RUN" if res.get("ok") else "FAILED",
                       "msg": _short(f"{src}: {res.get('found', 0)} finding(s)", 90),
                       "phase": PHASE_FOR_CLUSTER[cluster]})
        for i, ev in enumerate(by_source.get(src, [])[:12]):
            fid = f"{sid}_f{i}"
            nodes.append({"id": fid, "kind": "finding", "cluster": cluster, "parent": sid,
                          "label": _short(ev["title"], 48), "status": _STATUS.get(ev.get("status")),
                          "detail": _short(ev.get("snippet", ""), 160)})
            edges.append({"from": sid, "to": fid, "kind": "found"})
            if ev.get("status") == "confirmed":
                events.append({"tag": "VERIFY", "msg": _short(ev["title"], 90), "phase": 4})
    for ent in report.get("entities", []):
        if len(ent.get("sources", [])) >= 2:
            owners = [n["id"] for n in nodes if n["kind"] == "finding" and
                      n["parent"].removeprefix("src_") in ent["sources"]]
            for a, b in zip(owners, owners[1:]):
                if a.split("_f")[0] != b.split("_f")[0]:
                    edges.append({"from": a, "to": b, "kind": "cross-link"})
            events.append({"tag": "CROSS-LINK", "msg": _short(f"{ent['value']} x{len(ent['sources'])}", 90),
                           "phase": PHASE_MATCH})
    s = report.get("summary", {})
    nodes.append({"id": "report", "kind": "report", "cluster": "SYNTHESIS",
                  "label": f"report: {s.get('confirmed', 0)} confirmed / {s.get('findings', 0)}",
                  "status": "ok"})
    events.append({"tag": "SYNTH", "msg": f"case {report.get('case_id')} assembled", "phase": 5})
    return {"meta": {"source": "OpenAtlas case", "session_id": report.get("case_id"),
                     "target": t.get("value"), "ollama_host": Config.llm.host,
                     "model": profiles.active().text_model},
            "clusters": CLUSTERS, "nodes": nodes, "edges": edges, "events": events}
