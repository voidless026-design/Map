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

COMMANDS = {"investigate", "plan", "run", "catalog", "serve", "cases", "kb", "doctor", "ev"}


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


def cmd_plan(a: argparse.Namespace) -> int:
    """ATLAS loop, step 1: propose sources; prints the command so you decide whether to run it."""
    import shlex

    from openatlas.reasoning import loop

    p = loop.plan_case(a.target, a.purpose or "", a.type or "")
    if a.json:
        print(json.dumps(p, indent=2))
        return 0
    print(f"Auto-plan ({p['mode']}): {len(p['steps'])} of {len(p['available'])} sources - {p['why']}")
    for s in p["steps"]:
        print(f"  · {s}")
    purpose = a.purpose or "<purpose>"
    print("\nRun it:\n  openatlas investigate " + shlex.quote(a.target) + " --sources "
          + ",".join(p["steps"]) + " --purpose " + shlex.quote(purpose))
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
    if op == "where":
        return _kb_where()
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
            print(f"[{i}] {h['title']}  {h['url']}\n    why: {h['why']} (score {h['score']})"
                  f"\n    {h['snippet']}")
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
    if op == "library":
        return _kb_library(a)
    if op == "eval":
        from openatlas.kb import evaluate

        r = evaluate.eval_fixture() if a.fixture else evaluate.eval_brain(a.sample)
        if a.json:
            print(json.dumps(r, indent=2))
        else:
            print(r.get("note") or f"{r['queries']} queries: " + "  ".join(
                f"{k}={v}" for k, v in r["metrics"].items()))
            for f in r["failures"][:15]:
                print(f"  ✗ {f['q']!r}: wanted {f['wanted']}, got {f['got'][:3]}")
            print("search quality OK" if r["ok"] else "search quality BELOW thresholds "
                  + json.dumps(evaluate.THRESHOLDS))
        return 0 if r["ok"] else 1
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


def _size(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def _no_book(library: Any, row_id: int) -> int:
    ids = ", ".join(f"{b['id']} ({b['filename']})" for b in library.rows()) or "none yet"
    print(f"no book with id {row_id} - your books: {ids}")
    return 1


def _kb_where() -> int:
    from openatlas.kb import store

    w = store.where()
    state = "" if w["writable"] else "  <- NOT WRITABLE"
    print(f"data folder: {w['data_dir']}  ({w['free_gb']} GB free){state}")
    print(f"  OPENATLAS_DATA_DIR is {'set to ' + w['env'] if w['env'] else 'not set (using the default)'}")
    if not w["drives"]:
        print("no extra drives mounted. Plug the drive in and open it once in Files "
              "(that mounts it under /run/media), then run this again.")
        return 0
    print("drives you could use instead (copy ONE line into your terminal):")
    for d in w["drives"]:
        ok = "" if d["writable"] else "   (read-only for you - pick another)"
        print(f"  {d['mount']}  {d['fstype']}  {d['free_gb']} GB free{ok}")
        if d["writable"]:
            print(f"    echo \"{d['export']}\" >> ~/.bashrc && source ~/.bashrc")
    return 0


def _follow(library: Any, run: Any) -> Any:
    """Run a download/ingest in the foreground with a live progress line; Ctrl+C pauses it cleanly."""
    import threading

    done = threading.Event()
    tty = sys.stdout.isatty()

    def show() -> None:
        last = ""
        while not done.wait(5 if tty else 30):
            live = [r for r in library.rows() if r["status"] in ("downloading", "ingesting")]
            for r in live:
                line = library.progress_line(r) if r["status"] == "downloading" else \
                    f"{r['filename']}  feeding the brain {r['ingested'] or 0:,} articles"
                if line != last:
                    print(("\r" + line.ljust(100)) if tty else line, end="" if tty else "\n", flush=True)
                    last = line
        if tty and last:
            print()

    t = threading.Thread(target=show, daemon=True)
    t.start()
    try:
        return run()
    except KeyboardInterrupt:
        for r in library.rows():
            if r["status"] == "downloading":
                library.control(r["id"], "pause")
        print("\npaused - carry on later with: openatlas kb library resume")
        return "paused"
    finally:
        done.set()
        t.join(timeout=1)


def _background(library: Any) -> int:
    """Detach `kb library ingest` from the terminal so closing it doesn't stop the download."""
    import subprocess

    log = library.library_dir() / "download.log"
    with open(log, "ab") as fh:
        proc = subprocess.Popen([sys.executable, "-m", "openatlas.cli", "kb", "library", "ingest"],
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    print(f"downloading in the background (process {proc.pid}); you can close this terminal.")
    print(f"  progress:  openatlas kb library list      log: tail -f {log}")
    print(f"  stop it:   openatlas kb library pause     (or: kill {proc.pid})")
    return 0


def _kb_library(a: argparse.Namespace) -> int:
    """Kiwix library: offline encyclopedias for the brain (multi-GB, verified, no duplicates)."""
    from openatlas.kb import kiwix, library, store

    op = a.lib_cmd
    if op == "catalog":
        books, total = library.find_books(a.query or "", a.lang, a.max)
        for b in library.annotate(books):
            tag = {"have": "✓ have", "update": "↑ update", "new": ""}.get(b["status"], "")
            print(f"{_size(b['size']):>9}  {b['filename']:<48} {tag}")
        if not books:
            print("nothing found - try a single word such as: wikipedia, wiktionary, gutenberg")
        elif total > len(books):
            print(f"showing {len(books)} of {total}+ - add words or a name to narrow it, "
                  "e.g. openatlas kb library catalog wikipedia_en_all")
        else:
            print(f"{total} book(s). Download one with: openatlas kb library get {books[0]['book']}")
        return 0
    if op == "list":
        s = library.summary()
        print(f"library: {s['dir']}  ({s['free_gb']} GB free)  libzim={'yes' if s['libzim'] else 'no'}")
        for b in s["books"]:
            print(f"  [{b['id']}] {b['filename']:<48} {b['status']:<11} "
                  f"download {b['percent']}%  brain {b['ingest_percent']}%  {b['note'] or ''}")
        return 0
    if op == "get":
        try:
            book = library.resolve(a.name, a.lang)  # newest version of exactly that book
        except library.NotFound as exc:
            print(exc)
            for c in exc.choices[:30]:
                print(f"  openatlas kb library get {c}")
            if not exc.choices:
                print("see what exists with: openatlas kb library catalog wikipedia")
            return 1
        row_id = library.unfinished(book)
        if row_id:  # your own half-finished download of this file: carry on, don't refuse it
            library.requeue(row_id)
            print(f"resuming {book['filename']} from {_size(library.get(row_id)['bytes_done'])} "
                  f"of {_size(book['size'])} - Ctrl+C pauses")
        else:
            try:
                row_id = library.enqueue(book)
            except library.Duplicate as exc:
                print(f"not downloading: {exc}")
                return 0
            print(f"downloading {book['filename']} ({_size(book['size'])}) - Ctrl+C pauses, "
                  "openatlas kb library resume carries on")
        status = _follow(library, lambda: library.download(row_id))
        if status == "busy":
            print("another Atlas window is already downloading it - watch it with: openatlas kb library list")
            return 0
        if status == "paused":
            return 0
        print(f"{book['filename']}: {status} - {(library.get(row_id) or {}).get('note', '')}")
        if status == "ready" and not a.no_ingest:
            print("feeding the brain (resumable) ...")
            print(_follow(library, lambda: library.ingest(row_id)))
        return 0 if status == "ready" else 1
    if op == "ingest":
        library.adopt_existing()
        _follow(library, library.work)
        return 0
    if op in ("pause", "resume"):
        if a.id is not None:
            if library.get(a.id) is None:
                return _no_book(library, a.id)
            if op == "pause":
                row = library.control(a.id, op)
                print(f"[{a.id}] {row['filename']}: {row['status']}")
                return 0
            library.requeue(a.id)
            store.set_meta("library_paused", False)
            if a.background:
                return _background(library)
            print(f"resuming [{a.id}] {library.get(a.id)['filename']} here - Ctrl+C pauses")
            _follow(library, library.work)
            return 0
        if op == "pause":
            store.set_meta("library_paused", True)
            for r in library.rows():
                if r["status"] in ("queued", "downloading"):
                    library.control(r["id"], "pause")
            print("library downloads paused (all books)")
            return 0
        ids = library.resume_all()
        if not ids and not any(r["status"] in ("ready", "ingesting") for r in library.rows()):
            print("nothing to resume - see: openatlas kb library list")
            return 0
        if a.background:
            return _background(library)
        print(f"resuming {len(ids)} download(s) here - Ctrl+C pauses; "
              "add --background to keep going after you close the terminal")
        library.adopt_existing()
        _follow(library, library.work)
        return 0
    if op == "verify":
        if library.get(a.id) is None:
            return _no_book(library, a.id)
        r = library.verify(a.id)
        print(json.dumps(r, indent=2))
        return 0 if r.get("ok") else 1
    if op == "serve":
        if not kiwix.ensure():
            print(kiwix.HINT if not kiwix.binary() else "no verified books in the library yet")
            return 1
        print(f"Kiwix reader for {kiwix.status()['books']} book(s) at http://127.0.0.1:{kiwix.PORT}/kiwix/ "
              "(also inside Atlas: Library tab). Ctrl+C to stop.")
        try:
            kiwix._proc.wait()
        except KeyboardInterrupt:
            kiwix.stop()
        return 0
    return 2


def cmd_doctor(a: argparse.Namespace) -> int:
    from openatlas.utils.forge import cmd_doctor as forge_doctor

    return forge_doctor(a)


def cmd_ev(a: argparse.Namespace) -> int:
    from openatlas.ev import agent, memory, state, tools, voice
    from openatlas.llm import ollama_client

    op = a.ev_cmd
    if op == "status":
        d = ollama_client.diagnose()
        v = voice.status()
        m = state.mood()
        print(f"E.V · mood {m['label']} · rapport {m['rapport']:.2f}")
        print(f"  local model: {d['message']}")
        print(f"  hearing: {'faster-whisper ready' if v['stt']['available'] else v['stt']['hint']}")
        print(f"  voice:   {'MeloTTS ' + v['tts']['voice'] + ' ready' if v['tts']['available'] else v['tts']['hint']}")
        return 0
    if op == "voice-setup":
        try:
            py = voice.setup_sidecar()
        except Exception as exc:
            print(f"voice set-up stopped: {exc}")
            return 1
        print(f"voice environment ready: {py}")
        tts = voice.SidecarTTS()
        pcm = tts.synth("G'day! I'm E.V. My voice is all set up and running on your own computer.")
        out = voice.voice_dir().parent / "voice-test.wav"
        import wave

        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tts.rate)
            w.writeframes(pcm)
        tts.close()
        print(f"test phrase saved: {out}  (play it with: xdg-open {out})")
        return 0
    if op == "memory":
        if a.forget:
            gone = memory.forget(a.forget)
            print("forgot: " + ("; ".join(f["text"] for f in gone) if gone else "nothing matched"))
            return 0
        for f in memory.facts():
            print(f"  [{f['id']}] {f['text']}")
        if not memory.facts():
            print("E.V doesn't remember anything about you yet. Say \"remember that ...\" to teach her.")
        return 0
    if op == "approvals":
        for p in tools.pending():
            print(f"  [{p['id']}] {p['tool']} {json.dumps(p['args'])}  risk: {p['risk']['level']} - {p['risk']['feeling']}")
        if not tools.pending():
            print("nothing waiting for approval")
        return 0
    if op in ("approve", "deny"):
        try:
            r = tools.decide(a.id, op == "approve")
        except KeyError:
            print(f"no approval with id {a.id} - see: openatlas ev approvals")
            return 1
        print(f"[{a.id}] {r['tool']}: {r['status']}")
        if r.get("result"):
            print(json.dumps(r["result"], indent=2, default=str)[:3000])
        return 0 if r["status"] in ("done", "denied") else 1

    def one(conv: Optional[int], text: str) -> int:
        conv_id = conv
        for ev in agent.respond(conv, text):
            t = ev["type"]
            if t == "start":
                conv_id = ev["conv_id"]
            elif t == "token":
                print(ev["text"], end="", flush=True)
            elif t == "tool":
                print(f"\n  · {ev['skill']}: {ev['name']} {'ok' if ev['ok'] else ev.get('error')}", flush=True)
            elif t == "approval":
                print(f"\n  ? waiting for approval [{ev['id']}] {ev['tool']} ({ev['risk']['level']} risk) - "
                      f"openatlas ev approve {ev['id']}", flush=True)
            elif t == "notice":
                print(f"\n  ! {ev['text']}", flush=True)
            elif t == "qa":
                c = ev["counts"]
                print(f"\n  ✓ checked {ev['checked']} claim(s): {c['supported']} supported, "
                      f"{c['unsupported']} unsupported, {c['unverified']} unverified", end="")
        print()
        return conv_id or 0

    if a.message:
        one(None, a.message)
        return 0
    print("E.V here - type to chat, Ctrl+D to leave.")
    conv = None
    while True:
        try:
            text = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nsee ya!")
            return 0
        if text:
            print("E.V › ", end="")
            conv = one(conv, text)


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

    pl = sub.add_parser("plan", help="Auto-plan: propose which sources to run (ATLAS loop)")
    pl.add_argument("target")
    pl.add_argument("--purpose", help="why you are looking (a self-audit adds opt-in checks)")
    pl.add_argument("--type", help="force the target type")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_plan)

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
    x = ks.add_parser("library", help="Kiwix offline encyclopedias: catalog, download, feed the brain")
    ls = x.add_subparsers(dest="lib_cmd", required=True)
    y = ls.add_parser("catalog", help="search the official Kiwix catalog")
    y.add_argument("query", nargs="?", default="", help="words, or a name like wikipedia_en_all")
    y.add_argument("--lang", default="eng", help="eng, fra, deu ... or '' for all languages")
    y.add_argument("--max", type=int, default=60, help="how many to show")
    ls.add_parser("list", help="books in your library, download and brain progress")
    y = ls.add_parser("get", help="download a book (resumable, checksum-verified, never twice)")
    y.add_argument("name", help="book or file name, e.g. wikipedia_en_all_nopic")
    y.add_argument("--lang", default="")
    y.add_argument("--no-ingest", action="store_true", help="download only")
    ls.add_parser("ingest", help="feed verified books into the brain (resumes)")
    y = ls.add_parser("pause", help="pause one book (number from 'list') or, without a number, all downloads")
    y.add_argument("id", type=int, nargs="?")
    y = ls.add_parser("resume", help="carry on downloading (also after closing the terminal); "
                      "one book by number, or all")
    y.add_argument("id", type=int, nargs="?")
    y.add_argument("--background", action="store_true",
                   help="keep downloading after you close the terminal (log in the library folder)")
    y = ls.add_parser("verify", help="re-check a file against its published SHA-256")
    y.add_argument("id", type=int, help="the number in [brackets] from 'openatlas kb library list'")
    ls.add_parser("serve", help="read your books with Kiwix (kiwix-serve)")
    x = ks.add_parser("eval", help="measure search relevance (P@1, MRR, nDCG, off-topic rate)")
    x.add_argument("--fixture", action="store_true", help="use the built-in look-alike corpus")
    x.add_argument("--sample", type=int, default=200, help="articles to sample from your brain")
    x.add_argument("--json", action="store_true")
    x = ks.add_parser("graph", help="show the brain in the knowledge-graph visualizer")
    x.add_argument("--port", type=int, default=8765)
    x.add_argument("--no-serve", action="store_true", help="only write output/visualizer/")
    x = ks.add_parser("boost", help="learn this topic next")
    x.add_argument("topic")
    ks.add_parser("where", help="where the brain and books are stored, and drives you could move them to")
    kb.set_defaults(func=cmd_kb)

    ev = sub.add_parser("ev", help="E.V, your local AI companion: chat, voice set-up, memory")
    es = ev.add_subparsers(dest="ev_cmd", required=True)
    x = es.add_parser("chat", help="talk to E.V in the terminal (or send one message)")
    x.add_argument("message", nargs="?", default="", help="one message; omit for a conversation")
    es.add_parser("status", help="local model, voice and mood")
    es.add_parser("voice-setup", help="install E.V's Australian voice (MeloTTS EN-AU) in its own venv")
    x = es.add_parser("memory", help="what E.V remembers about you")
    x.add_argument("--forget", default="", help="forget facts matching these words (or an id)")
    es.add_parser("approvals", help="actions waiting for your approval")
    x = es.add_parser("approve", help="approve (run) a pending action")
    x.add_argument("id", type=int)
    x = es.add_parser("deny", help="deny a pending action")
    x.add_argument("id", type=int)
    ev.set_defaults(func=cmd_ev)

    d = sub.add_parser("doctor", help="automatically verify every tool the skills use")
    d.add_argument("--live", action="store_true", help="also probe public sources from this network")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    from openatlas.kb.store import DataDirError

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except DataDirError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
