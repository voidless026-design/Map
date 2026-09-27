"""Subcommand CLI: ``openatlas investigate|run|catalog|serve|cases|kb|doctor``.

Every button in the web GUI maps to one of these commands (the GUI shows the exact
command it autofills), so anything you can click you can also script.
The legacy OAtlas-style flags (``openatlas -f ...``) are still handled by ``main.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

COMMANDS = {"investigate", "run", "catalog", "serve", "cases", "kb", "doctor"}


def _kv(pairs: Optional[List[str]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        if not k or not _:
            raise SystemExit(f"--arg expects key=value, got '{p}'")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


def _print_progress(ev: Dict[str, Any]) -> None:
    kind = ev.get("type")
    if kind == "source_done":
        r = ev.get("result", {})
        state = r.get("error") or f"{r.get('found', 0)} findings"
        print(f"  · {r.get('source', '?'):<16} {state}", file=sys.stderr)
    elif kind == "stage":
        print(f"  » {ev.get('message') or ev.get('stage', '')}", file=sys.stderr)


def _investigate(value: str, *, purpose: str, filter_id: str = "", sources: Optional[List[str]] = None,
                 forced_type: Optional[str] = None, name: str = "", summarize: Optional[bool] = None,
                 deadline: float = 150.0, quiet: bool = False) -> Dict[str, Any]:
    from openatlas.investigate.pipeline import run_investigation

    return asyncio.run(run_investigation(
        value, purpose=purpose, name=name, forced_type=forced_type, filter_id=filter_id,
        source_ids=sources, summarize=summarize, deadline=deadline,
        emit=(lambda _e: None) if quiet else _print_progress))


def _emit_report(report: Dict[str, Any], as_json: bool, as_md: bool) -> None:
    from openatlas.investigate.report import to_markdown

    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(to_markdown(report))


def cmd_investigate(a: argparse.Namespace) -> int:
    sources = [s.strip() for s in a.sources.split(",") if s.strip()] if a.sources else None
    try:
        report = _investigate(a.target, purpose=a.purpose, filter_id=a.filter or "", sources=sources,
                              forced_type=a.type, name=a.name or "",
                              summarize=False if a.no_summary else None, deadline=a.deadline,
                              quiet=a.json)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit_report(report, a.json, a.md)
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    from openatlas import catalog

    action = catalog.find(a.slug)
    if action is None:
        print(f"unknown action '{a.slug}'. See: openatlas catalog", file=sys.stderr)
        return 2
    if action["kind"] == "source":
        if not a.purpose:
            print("error: sources are investigations - add --purpose \"why you are looking\"",
                  file=sys.stderr)
            return 2
        report = _investigate(a.value, purpose=a.purpose, sources=[a.slug], summarize=False,
                              quiet=a.json)
        _emit_report(report, a.json, not a.json)
        return 0
    from openatlas.config import Config

    Config.settings.authorized_target = bool(a.authorized_target)
    result = catalog.run_tool(action, a.value, _kv(a.arg))
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success", True) else 1


def cmd_catalog(a: argparse.Namespace) -> int:
    from openatlas import catalog

    data = catalog.catalog()
    if a.json:
        print(json.dumps(data, indent=2))
        return 0
    for f in data["filters"]:
        acts = [x for x in data["actions"] if f["id"] in x["filters"]]
        if a.filter and a.filter != f["id"]:
            continue
        print(f"\n{f['label'].upper()}  ({len(acts)})")
        for x in acts:
            tag = "source" if x["kind"] == "source" else "tool  "
            print(f"  {tag}  {x['slug']:<22} {x['title']}")
    print("\nRun one:   openatlas run <slug> <value>"
          "\nOr all:    openatlas investigate \"<target>\" --purpose \"...\" [--filter <id>]")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from openatlas.web.server import serve

    return serve(host=a.host, port=a.port, open_browser=not a.no_browser, brain=a.brain)


def cmd_cases(a: argparse.Namespace) -> int:
    from openatlas.core.database import db_funcs
    from openatlas.investigate.report import to_markdown

    if a.case_id:
        case = db_funcs.get_case(a.case_id)
        if not case:
            print(f"no case '{a.case_id}'", file=sys.stderr)
            return 1
        report = case.get("report") or {}
        print(to_markdown(report) if a.md and report.get("target") else json.dumps(case, indent=2, default=str))
        return 0
    rows = db_funcs.list_cases(limit=a.limit)
    if not rows:
        print("no cases yet - try: openatlas investigate \"<target>\" --purpose \"...\"")
    for r in rows:
        print(f"{r['case_id']}  {str(r.get('created_at', ''))[:16]}  {r.get('status', ''):<8} "
              f"{r.get('target_type', ''):<9} {r.get('target', '')}  - {r.get('purpose', '')}")
    return 0


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def cmd_kb(a: argparse.Namespace) -> int:
    from openatlas.kb import ingest, store, taxonomy

    op = a.kb_cmd
    if op == "seeds":
        seeds = taxonomy.parse(a.file)
        for div, n in taxonomy.divisions(seeds).items():
            print(f"{n:>5}  {div}")
        print(f"{len(seeds):>5}  unique seeds")
        return 0
    if op == "plan":
        print(json.dumps(ingest.plan(taxonomy.parse(a.file), a.max_tier)))
        return 0
    if op == "ingest":
        if not ingest.next_task():
            ingest.plan(taxonomy.parse(), a.max_tier)
        done = asyncio.run(ingest.run(max_tasks=a.max, rate=a.rate, idle_exit=True))
        print(json.dumps(done))
        return 0
    if op == "daemon":
        from openatlas.kb import daemon

        if not ingest.next_task():
            ingest.plan(taxonomy.parse(), 3)
        return daemon.main()
    if op == "stats":
        p = ingest.progress()
        if a.json:
            print(json.dumps(p, indent=2, default=str))
            return 0
        print(f"brain:     {p['path']}  ({_human_bytes(p['bytes'])})")
        print(f"articles:  {p['articles']}   cases: {p['cases']}   chunks: {p['chunks']}   "
              f"vectors: {p['vectors']}")
        print(f"progress:  {p['percent']}%  ({p['finished']}/{p['queued']} queued tasks)")
        for t in p.get("tiers", []):
            print(f"  tier {t['tier']}  {t['name']:<24} {t['done']}/{t['total']}")
        return 0
    if op == "search":
        from openatlas.kb import retrieve

        hits = retrieve.search(a.query, k=a.k)
        for i, h in enumerate(hits, 1):
            print(f"[{i}] {h['title']}  {h['url']}\n    {h['snippet']}")
        if not hits:
            print("no hits (the topic has been queued for learning)")
            ingest.boost(a.query)
        return 0
    if op == "ask":
        from openatlas.kb import ask

        r = ask.ask(a.question)
        print(r["answer"])
        for c in r["citations"]:
            print(f"  [{c['n']}] {c['title']} - {c['url']} ({c['license']})")
        return 0
    if op in ("pause", "resume"):
        store.set_meta("paused", op == "pause")
        print("paused" if op == "pause" else "resumed")
        return 0
    if op == "graph":
        from openatlas.utils import knowledge_graph

        graph = knowledge_graph.build_graph_from_brain()
        out = knowledge_graph.write_bundle(graph)
        print(f"brain graph: {len(graph['nodes'])} nodes -> {out}")
        if not a.no_serve:
            knowledge_graph.serve(out, port=a.port)
        return 0
    if op == "boost":
        print(f"queued {ingest.boost(a.topic)} task(s) for '{a.topic}'")
        return 0
    return 2


def cmd_doctor(a: argparse.Namespace) -> int:
    from openatlas.utils.forge import cmd_doctor as forge_doctor

    return forge_doctor(a)


def build_parser() -> argparse.ArgumentParser:
    from openatlas.investigate.sources import FILTERS

    p = argparse.ArgumentParser(prog="openatlas", description="Free, local OSINT toolkit.")
    sub = p.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("investigate", help="run a full evidence-based investigation")
    inv.add_argument("target", help="name, username, email, phone, domain, URL, IP or image path")
    inv.add_argument("--purpose", required=True, help="why you are looking (stored with the case)")
    inv.add_argument("--filter", choices=sorted(FILTERS), help="only sources in this filter")
    inv.add_argument("--sources", help="comma-separated source slugs (see: openatlas catalog)")
    inv.add_argument("--type", help="force the target type (person, username, email, ...)")
    inv.add_argument("--name", help="case name")
    inv.add_argument("--deadline", type=float, default=150.0, help="overall seconds (default 150)")
    inv.add_argument("--no-summary", action="store_true", help="skip the local-AI summary")
    fmt = inv.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--md", action="store_true", help="Markdown report (default)")
    inv.set_defaults(func=cmd_investigate)

    run = sub.add_parser("run", help="run one action by slug (what a GUI button does)")
    run.add_argument("slug")
    run.add_argument("value")
    run.add_argument("--arg", action="append", help="extra parameter key=value (repeatable)")
    run.add_argument("--purpose", help="required when the slug is a source")
    run.add_argument("--json", action="store_true")
    run.add_argument("--authorized-target", action="store_true",
                     help="you are authorised to actively scan this target")
    run.set_defaults(func=cmd_run)

    cat = sub.add_parser("catalog", help="list every action grouped by filter")
    cat.add_argument("--filter", choices=sorted(FILTERS))
    cat.add_argument("--json", action="store_true")
    cat.set_defaults(func=cmd_catalog)

    srv = sub.add_parser("serve", help="start the web GUI (loopback only by default)")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8600)
    srv.add_argument("--no-browser", action="store_true")
    srv.add_argument("--brain", action="store_true", help="also grow the brain in the background")
    srv.set_defaults(func=cmd_serve)

    cs = sub.add_parser("cases", help="list cases or show one")
    cs.add_argument("case_id", nargs="?")
    cs.add_argument("--md", action="store_true")
    cs.add_argument("--limit", type=int, default=50)
    cs.set_defaults(func=cmd_cases)

    kb = sub.add_parser("kb", help="the brain: an ever-growing local knowledge base")
    ks = kb.add_subparsers(dest="kb_cmd", required=True)
    x = ks.add_parser("seeds", help="show the fields-of-study seeds per division")
    x.add_argument("--file")
    x = ks.add_parser("plan", help="queue seeds + tiers")
    x.add_argument("--file")
    x.add_argument("--max-tier", type=int, default=3, choices=range(0, 4))
    x = ks.add_parser("ingest", help="ingest a batch now, then exit")
    x.add_argument("--max", type=int, default=50)
    x.add_argument("--rate", type=float, help="requests per second (default from profile)")
    x.add_argument("--max-tier", type=int, default=3, choices=range(0, 4))
    ks.add_parser("daemon", help="grow the brain forever (use the systemd unit)")
    x = ks.add_parser("stats", help="size, progress and tiers")
    x.add_argument("--json", action="store_true")
    x = ks.add_parser("search", help="full-text + vector search")
    x.add_argument("query")
    x.add_argument("-k", type=int, default=8)
    x = ks.add_parser("ask", help="answer a question with citations")
    x.add_argument("question")
    ks.add_parser("pause", help="pause ingestion")
    ks.add_parser("resume", help="resume ingestion")
    x = ks.add_parser("graph", help="show the brain in the knowledge-graph visualizer")
    x.add_argument("--port", type=int, default=8765)
    x.add_argument("--no-serve", action="store_true", help="only write output/visualizer/")
    x = ks.add_parser("boost", help="learn this topic next")
    x.add_argument("topic")
    kb.set_defaults(func=cmd_kb)

    d = sub.add_parser("doctor", help="automatically verify every tool the skills use")
    d.add_argument("--live", action="store_true", help="also probe public sources from this network")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
