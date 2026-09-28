"""``forge doctor``: automatically verify every tool the skills depend on.

Each check feeds the tool a known-good AND a known-bad fixture and confirms it tells them
apart - so a tool that silently stopped working (e.g. a validator that passes everything)
is caught. Nothing here patches globals, so it is safe to run inside the live server.

``live=True`` additionally probes each public data source once from *your* network and
reports which ones answer (this is the only part that uses the internet).
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import httpx

from openatlas.config import Config

Check = Tuple[str, Callable[[], Tuple[str, str]]]  # name, fn -> (status, detail)


def _pass(detail: str) -> Tuple[str, str]:
    return "pass", detail


def _fail(detail: str) -> Tuple[str, str]:
    return "fail", detail


def check_schema_validator() -> Tuple[str, str]:
    from openatlas.utils.schema_validate import validate_methods_yaml

    good = validate_methods_yaml()
    with tempfile.TemporaryDirectory() as d:
        bad_yaml = Path(d) / "bad.yaml"
        bad_yaml.write_text("E:\n  functions:\n    f:\n      arguments:\n        x: {type: blob}\n")
        bad = validate_methods_yaml(str(bad_yaml), check_registry=False)
    if good["ok"] and not bad["ok"] and len(bad["errors"]) >= 2:
        return _pass("real methods.yaml valid; broken fixture rejected")
    return _fail(f"good ok={good['ok']} ({good['errors'][:2]}), bad ok={bad['ok']}")


def check_toolresult_validator() -> Tuple[str, str]:
    from openatlas.core.registry import ToolResult
    from openatlas.utils.schema_validate import validate_tool_result

    good = validate_tool_result(ToolResult("t", {"a": 1}))
    bad = validate_tool_result(ToolResult("t", {"a": 1}, success=False))  # failure w/o error
    return _pass("accepts valid, rejects error-less failure") if good["ok"] and not bad["ok"] \
        else _fail(f"good={good}, bad={bad}")


def check_smoke_runner() -> Tuple[str, str]:
    from openatlas.utils.smoke_run import verify_function

    r = verify_function("verify_email_address")
    missing = verify_function("definitely_not_a_function")
    if r["ok"] and not missing["ok"]:
        return _pass(f"{len(r['checks'])} checks on a real tool; unknown tool rejected")
    return _fail(f"real tool report: {[c for c in r['checks'] if not c['ok']]}")


def check_robots_guard() -> Tuple[str, str]:
    from openatlas.utils.robots import allowed_by

    rules = "User-agent: *\nDisallow: /private\n"
    if allowed_by(rules, "https://x.example/public") and not allowed_by(rules, "https://x.example/private/a"):
        return _pass("allows /public, blocks /private")
    return _fail("robots rules not applied")


def check_secret_lint() -> Tuple[str, str]:
    from openatlas.utils.secret_lint import (
        default_target,
        iter_files,
        scan_path,
        scan_text,
        stray_copies,
    )

    planted = scan_text('api_key = "' + "sk-" + "a1b2c3d4" * 4 + '"')
    clean = scan_text("def ok():\n    return 'nothing secret here'\n")
    # Always the installed package (absolute path): the result must not depend on the folder
    # you run `openatlas doctor` from, and must never scan a virtualenv's site-packages.
    target = default_target()
    n_files = len(iter_files(target, package=True))
    repo = scan_path(target, package=True)
    strays = stray_copies(target)
    if planted and not clean and n_files and not repo:
        detail = f"planted key caught; clean text passes; {n_files} package files clean"
        if strays:  # e.g. an old copy of the repo unpacked inside the package folder
            return "warn", (detail + f"; skipped {len(strays)} thing(s) inside the package folder that "
                            "aren't part of it (an old copy?): " + ", ".join(s.name for s in strays)
                            + " - check, then remove with: rm -rf " + " ".join(f"'{s}'" for s in strays))
        return _pass(detail)
    where = "; ".join(f"{f['source']}:{f['line']} ({f['rule']})" for f in repo[:3])
    return _fail(f"planted caught={bool(planted)} clean flagged={bool(clean)} files={n_files} "
                 f"findings={len(repo)} {where}")


def check_scaffolder() -> Tuple[str, str]:
    """Generate a throwaway engine in a temp dir, load it, verify it, unload it."""
    import importlib.util

    from openatlas.core.registry import ToolRegistry, ToolResult
    from openatlas.utils import forge
    from openatlas.utils.schema_validate import validate_methods_yaml

    name = f"DoctorProbe{int(time.time() * 1000) % 10**8}Engine"
    common = f"doctor-probe-{id(name)}"
    with tempfile.TemporaryDirectory() as d:
        paths = forge.Paths(tools_dir=Path(d), methods_yaml=Path(d) / "methods.yaml",
                            tests_dir=Path(d), tools_init=Path(d) / "__init__.py")
        paths.methods_yaml.write_text("")
        paths.tools_init.write_text("")
        module = forge.scaffold_engine(engine=name, common_name=common, abbrev="dpE",
                                       function="doctor_probe", description="self-test engine",
                                       backend="local", paths=paths)
        spec = importlib.util.spec_from_file_location(f"_doctor_{module}", Path(d) / f"{module}.py")
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            engine = ToolRegistry.engines()[common]
            res = engine.get_callable("doctor_probe")(target="x")
            schema = validate_methods_yaml(str(paths.methods_yaml), check_registry=False)
        finally:
            ToolRegistry._engines.pop(common, None)
    ok = isinstance(res, ToolResult) and schema["ok"] and (Path(d).exists() is False)
    return _pass("scaffold → import → registry → ToolResult → schema, all in a temp dir") if ok \
        else _fail(f"result={type(res).__name__} schema={schema}")


def check_skill_linter() -> Tuple[str, str]:
    from openatlas.skills import linter, registry

    skills = registry.list_skills()
    real = [s for s in skills if not s["lint_ok"]]
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "Bad_Skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: Bad_Skill\ndescription: x\n---\n# nothing\n")
        rejected = not linter.lint_skill(str(bad), run_commands=False)["ok"]
        weak = Path(d) / "weak-skill"  # an OpenAtlas skill must still meet the house rules
        weak.mkdir()
        (weak / "SKILL.md").write_text("---\nname: weak-skill\ndescription: does things\nmetadata:\n"
                                       "  project: OpenAtlas\n---\n# weak\n")
        rejected = rejected and not linter.lint_skill(str(weak), run_commands=False)["ok"]
    ext = [s["name"] for s in skills if s.get("external")]
    if not real and rejected:
        note = (f"; {len(ext)} external skill(s) checked against the Agent Skills spec only: {', '.join(ext)}"
                if ext else "")
        return _pass(f"{len(skills) - len(ext)} project skills valid; broken skill rejected{note}")
    if not real:
        return _fail("broken fixture was accepted")
    names = ", ".join(s["name"] for s in real)
    detail = " | ".join(f"{s['name']}: {'; '.join(s['errors'])}" for s in real)
    return _fail(f"{len(real)} skill(s) fail verification ({names}). Fix them, or move them to "
                 f".claude/skill-drafts/ and re-run `python -m openatlas.utils.forge verify-skill "
                 f"<name>`. Details: {detail}")


def check_evidence_verifier() -> Tuple[str, str]:
    """osint-verify engine: a live profile is confirmed, a 404 is refuted, a page lacking the
    username stays unverified."""
    from openatlas.investigate.detect import detect
    from openatlas.investigate.models import Evidence
    from openatlas.investigate.verify import recheck_account
    from openatlas.net.client import Net

    pages = {"/real": (200, "profile of janedoe"), "/gone": (404, "no"), "/vague": (200, "welcome")}

    def handler(req: httpx.Request) -> httpx.Response:
        code, body = pages.get(req.url.path, (404, ""))
        return httpx.Response(code, content=body.encode())

    async def go() -> List[Any]:
        t = detect("janedoe")
        evs = [Evidence("whatsmyname", "account", p, url=f"https://site.example{p}") for p in pages]
        async with Net(transport=httpx.MockTransport(handler), robots_check=lambda u: True) as net:
            for e in evs:
                await recheck_account(net, t, e)
        return [e.verified for e in evs]

    got = asyncio.run(go())
    return _pass("confirmed / refuted / unverified as expected") if got == [True, False, None] \
        else _fail(f"got {got}, expected [True, False, None]")


def check_net_policy() -> Tuple[str, str]:
    from openatlas.net.client import Net

    seen: Dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, content=b"x" * 4096)

    async def go() -> Tuple[Any, Any]:
        async with Net(transport=httpx.MockTransport(handler), robots_check=lambda u: True) as net:
            broker = await net.get("https://www.spokeo.com/x", page=True)
            capped = await net.get("https://ok.example/", headers={"Authorization": "x"}, max_bytes=1024)
            return broker, capped

    broker, capped = asyncio.run(go())
    ok = broker.error and "data-broker" in broker.error and capped.truncated and seen.get("auth") is None
    return _pass("data brokers skipped, credentials stripped, body capped") if ok else \
        _fail(f"broker={broker.error} truncated={capped.truncated} auth={seen.get('auth')}")


def check_local_ai() -> Tuple[str, str]:
    from openatlas.llm import ollama_client
    from openatlas.runtime.resources import detect

    # the model picker on fixtures first: a missing model must never become an HTTP 404 again
    cases = [(["llama3.1:8b", "nomic-embed-text:latest"], "llama3.1:8b", "llama3.1:8b"),
             (["llama3.1:latest"], "llama3.1:8b", "llama3.1:latest"),
             (["qwen3:8b", "nomic-embed-text:latest", "llava:7b"], "llama3.1:8b", "qwen3:8b"),
             (["nomic-embed-text:latest"], "llama3.1:8b", None), ([], "llama3.1:8b", None)]
    saved = ollama_client._TAGS
    try:
        bad = []
        for tags, want, expect in cases:
            ollama_client._TAGS = (time.monotonic(), tags) if tags else (0.0, [])
            if tags and ollama_client.resolve_model(want) != expect:
                bad.append(f"{tags} -> {ollama_client.resolve_model(want)}")
    finally:
        ollama_client._TAGS = saved
    if bad:
        return _fail("model picker chose wrong: " + "; ".join(bad))
    diag = ollama_client.diagnose()
    if diag["reason"] == "not_running":
        return "warn", "model picker verified; local AI (Ollama) offline - optional; start it with `ollama serve`"
    if not diag["ok"]:
        return "warn", "model picker verified; " + diag["message"]
    rep = ollama_client.gpu_report()
    cpu = [m["model"] for m in rep["models"] if not m["on_gpu"]]
    if detect().gpus and cpu:
        return "warn", f"GPU present but {', '.join(cpu)} running on CPU - check GPU drivers"
    return _pass(diag["message"] + f"; {len(rep['models'])} loaded")


_BRAIN_FIXTURE = ("Doctor fixture: Topological quantum field theory",
                  "A topological quantum field theory is a quantum field theory which computes "
                  "topological invariants. It links knot theory, low-dimensional topology and "
                  "mathematical physics. " * 4)


def check_brain() -> Tuple[str, str]:
    """Self-test the brain's store + search on a throwaway brain (known-good / known-bad), then
    report on your real brain - sampling one of its articles when it has any."""
    from openatlas.kb import retrieve, store

    title, text = _BRAIN_FIXTURE
    with tempfile.TemporaryDirectory() as d, store.use_path(Path(d) / "brain.sqlite"):
        store.upsert_document(key="doctor:fixture", source="wikipedia", title=title, text=text,
                              url="https://example.org/fixture", license="CC BY-SA 4.0")
        found = any(h["key"] == "doctor:fixture"
                    for h in retrieve.search("topological quantum field theory", k=5,
                                             use_vectors=False))
        nonsense = retrieve.search("zqxjv wqpfk", k=5, use_vectors=False)
        # titles that used to trip the parser: a hyphen is not "-exclude", "C++" is not "C"
        tricky = ["Nil-Coxeter algebra", "C++", "C#", "C (programming language)"]
        for t in tricky:
            store.upsert_document(key=f"doctor:{t}", source="wikipedia", title=t, text=f"{t} is a topic. " * 6)
        tricky_miss = [t for t in tricky if (retrieve.search(t, k=5, use_vectors=False) or [{}])[0].get("title") != t]
    if not found or nonsense or tricky_miss:
        return _fail(f"self-test: fixture found={found}, nonsense query returned {len(nonsense)} hits, "
                     f"titles not ranked first: {tricky_miss}")

    with store.connect() as con:
        n = con.execute("SELECT COUNT(*) FROM documents WHERE source='wikipedia'").fetchone()[0]
        rows = con.execute("SELECT title, key FROM documents WHERE source='wikipedia' "
                           "ORDER BY RANDOM() LIMIT 5").fetchall()
    if not rows:
        return _pass("store + search self-test ok; your brain has 0 articles yet - grow it with "
                     "`openatlas kb ingest` or 'Grow the brain'")
    misses = []
    for row in rows:  # each article must come back for its own title
        hits = retrieve.search(row["title"], k=5, use_vectors=False)
        if not any(h["key"] == row["key"] for h in hits):
            misses.append(f"'{row['title']}' (got: {', '.join(h['title'] for h in hits[:3]) or 'nothing'})")
    if not misses:
        return _pass(f"self-test ok; {n:,} articles, {len(rows)} random ones (e.g. '{rows[0]['title']}') "
                     "each found by their own title")
    return _fail(f"your brain: {len(misses)}/{len(rows)} not found for their own title: " + "; ".join(misses)
                 + " - run `openatlas kb eval` for the full picture")


def check_search_relevance() -> Tuple[str, str]:
    """Known-good / known-bad: the real ranker must stay on-topic on a corpus full of
    look-alikes, and the old any-word ranker must FAIL the same evaluation - proving the
    evaluator can still catch an off-topic regression."""
    from openatlas.kb import evaluate

    good = evaluate.eval_fixture()
    bad = evaluate.eval_fixture(evaluate.legacy_or_search)
    m = good["metrics"]
    if good["ok"] and not bad["ok"]:
        return _pass(f"P@1 {m['p_at_1']}, MRR {m['mrr']}, off-topic {m['off_topic']:.0%} on "
                     f"{good['queries']} look-alike queries; old ranker correctly rejected "
                     f"({bad['metrics']['off_topic']:.0%} off-topic)")
    if not good["ok"]:
        worst = "; ".join(f"{f['q']} -> {f['got'][:3]}" for f in good["failures"][:3])
        return _fail(f"search drifts off-topic: {m} - {worst}")
    return _fail("evaluator accepted the known-bad ranker - it can no longer detect drift")


def check_library() -> Tuple[str, str]:
    """Kiwix library on fixtures: duplicate rules, checksum gate, and resume = identical file."""
    import hashlib

    from openatlas.kb import kiwix, library, store

    data = bytes(range(256)) * 4096  # 1 MiB fake ZIM body
    sha = hashlib.sha256(data).hexdigest()
    base = "https://download.kiwix.org/zim/wikipedia/"

    # a catalog like library.kiwix.org: the word search never matches file names, and the book
    # wanted sits on the second page - finding it by name must still work
    files = [f"wikipedia_en_topic{i}_nopic_2026-07.zim" for i in range(105)] + \
            ["wikipedia_en_all_nopic_2026-03.zim", "wikipedia_en_all_nopic_2026-06.zim",
             "wikipedia_en_all_maxi_2026-06.zim"]

    def opds(req: httpx.Request) -> httpx.Response:
        p = req.url.params
        hits = files if p.get("q", "wikipedia") == "wikipedia" else []
        start, count = int(p.get("start", 0)), int(p.get("count", 10))
        body = "".join(f'<entry><id>urn:uuid:{fn}</id><title>Wikipedia</title><language>eng</language>'
                       f'<link type="application/x-zim" href="{base}{fn}.meta4" length="1"/></entry>'
                       for fn in hits[start:start + count])
        return httpx.Response(200, content=f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode())

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url).startswith(library.CATALOG):
            return opds(req)
        name = str(req.url).rsplit("/", 1)[-1]
        if name.endswith(".meta4"):
            good = "bad" not in name
            xml = ('<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="f"><hash '
                   f'type="sha-256">{sha if good else "0" * 64}</hash><url>{base}{name[:-6]}</url>'
                   '</file></metalink>')
            return httpx.Response(200, content=xml.encode())
        rng = req.headers.get("range")
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        return httpx.Response(206 if rng else 200, content=data[start:])

    def entry(fn: str) -> Dict[str, Any]:
        b, v = library.split_filename(fn)
        return {"uuid": fn, "filename": fn, "book": b, "version": v, "url": base + fn,
                "meta4": base + fn + ".meta4", "size": len(data)}

    saved = library.TRANSPORT
    library.TRANSPORT = httpx.MockTransport(handler)
    try:
        with tempfile.TemporaryDirectory() as d, store.use_path(Path(d) / "brain.sqlite"):
            rid = library.enqueue(entry("wikipedia_en_x_2026-01.zim"))
            Path(library.get(rid)["path"] + ".part").write_bytes(data[:300_000])  # interrupted
            resumed = library.download(rid) == "ready" and library.verify(rid)["ok"] is True
            dup_refused = False
            try:
                library.check_duplicate(entry("wikipedia_en_x_2026-01.zim"))
            except library.Duplicate:
                dup_refused = True
            update_ok = library.check_duplicate(entry("wikipedia_en_x_2026-05.zim")) == rid
            bad = library.enqueue(entry("wikipedia_en_bad_2026-01.zim"))
            corrupt_rejected = library.download(bad) == "failed"
            by_name = library.resolve("wikipedia_en_all_nopic")["filename"] == "wikipedia_en_all_nopic_2026-06.zim"
            try:
                library.resolve("wikipedia_en_all")
                ambiguous_listed = False
            except library.NotFound as exc:
                ambiguous_listed = len(exc.choices) == 2
    finally:
        library.TRANSPORT = saved
    checks = {"resume gives the verified file": resumed, "duplicate refused": dup_refused,
              "newer version = update": update_ok, "corrupt download rejected": corrupt_rejected,
              "book found by name past page 1": by_name, "ambiguous name lists choices": ambiguous_listed}
    failed = [k for k, v in checks.items() if not v]
    if failed:
        return _fail("; ".join(failed) + " - FAILED")
    extras = []
    if not library.libzim_available():
        extras.append("feeding the brain needs: pip install libzim")
    if not kiwix.binary():
        extras.append("reading inside Atlas needs: sudo dnf install kiwix-tools")
    detail = "resume + checksum + duplicate rules + lookup by name verified"
    return ("warn", f"{detail}; {'; '.join(extras)}") if extras else _pass(detail)


# import name for each core dependency whose module name differs from its package name
_IMPORT_NAME = {"dnspython": "dns", "beautifulsoup4": "bs4", "pillow": "PIL", "python-dotenv": "dotenv",
                "pyyaml": "yaml", "python-docx": "docx"}


def core_dependencies() -> List[str]:
    """Required (non-optional) packages from this checkout's pyproject.toml."""
    pyproject = Path(Config.files.project_root) / "pyproject.toml"
    if not pyproject.exists():
        return []
    text = pyproject.read_text()
    try:
        import tomllib
    except ImportError:  # Python 3.10: the table is flat `name = spec` lines, read them directly
        body = re.search(r"^\[tool\.poetry\.dependencies\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
        lines = [ln.split("#", 1)[0].strip() for ln in (body.group(1) if body else "").splitlines()]
        return [ln.split("=", 1)[0].strip().strip('"') for ln in lines
                if "=" in ln and not ln.startswith("python ") and not re.search(r"optional\s*=\s*true", ln)]
    deps = tomllib.loads(text)["tool"]["poetry"]["dependencies"]
    return [n for n, spec in deps.items() if n != "python" and not (isinstance(spec, dict) and spec.get("optional"))]


def check_installation() -> Tuple[str, str]:
    """Is every package this checkout needs actually installed? (After `git pull`, new
    dependencies only arrive with `pip install -e .` - run in the checkout's own folder.)"""
    import importlib.util

    root = Path(Config.files.project_root)
    missing = [n for n in core_dependencies()
               if importlib.util.find_spec(_IMPORT_NAME.get(n, n).replace("-", "_")) is None]
    if missing:
        return _fail(f"not installed: {', '.join(missing)} - the code was updated but its packages weren't. "
                     f"Run: cd '{root}' && pip install -e .   (add '.[voice]' for E.V's hearing)")
    return _pass(f"all {len(core_dependencies()) or 'core'} required packages installed for {root}")


def _ev_sandbox():  # type: ignore[no-untyped-def]
    """A throwaway brain + E.V store (persona, memory, approvals) for self-tests."""
    from contextlib import contextmanager

    from openatlas.ev import db as ev_db
    from openatlas.kb import store

    @contextmanager
    def box():  # type: ignore[no-untyped-def]
        with tempfile.TemporaryDirectory() as d, store.use_path(Path(d) / "brain.sqlite"):
            ev_db.reset_init_cache()
            try:
                yield Path(d)
            finally:
                ev_db.reset_init_cache()
    return box()


def check_ev_gate() -> Tuple[str, str]:
    """E.V's approval gate, ethics screen and risk simulation on fixtures."""
    from openatlas.ev import tools

    with _ev_sandbox():
        r = tools.run("create_project", {"name": "doctor-probe", "kind": "notes", "path": "/nonexistent-doctor"})
        gated = bool(r.get("pending")) and not Path("/nonexistent-doctor").exists()
        risky = r.get("approval", {}).get("risk", {}).get("level") in ("medium", "high")
        denied = tools.decide(r["approval"]["id"], False)["status"] == "denied" if gated else False
        refused = bool(tools.run("search_brain", {"query": "bypass the paywall on example.com"}).get("refused"))
        read_ok = tools.run("recall", {"query": "anything"}).get("ok") is True
        n_tools, n_skills = len(tools.load_skills()), len(tools.skills())
    checks = {"write needs approval": gated, "risk appraised": risky, "deny leaves it undone": denied,
              "unethical request refused": refused, "read tools run": read_ok, "8 skills": n_skills == 8}
    bad = [k for k, v in checks.items() if not v]
    return _fail("; ".join(bad) + " - FAILED") if bad else \
        _pass(f"{n_tools} tools in {n_skills} skills; writes/commands/network wait for approval; refusals work")


def check_ev_qa() -> Tuple[str, str]:
    """The claim checker must pass a supported claim and flag a planted false one."""
    from openatlas.ev.skills import qa

    src = [{"title": "Fixture", "text": "The Murray River is 2,508 kilometres long and flows into the Southern Ocean."}]
    good = qa.check("The Murray River is 2,508 kilometres long and flows into the Southern Ocean [1].", src, use_model=False)
    bad = qa.check("The Murray River is 9,000 kilometres long and flows into the Southern Ocean [1].", src, use_model=False)
    none = qa.check("Platypuses were first described by Roman naturalists in the second century.", src, use_model=False)
    ok = (good["counts"]["supported"] == 1 and bad["counts"]["unsupported"] == 1
          and none["counts"]["unverified"] == 1)
    return _pass("supported / unsupported (planted wrong number) / unverified all labelled correctly") if ok else \
        _fail(f"claim checker mislabelled: {good['counts']} {bad['counts']} {none['counts']}")


def check_ev_documents() -> Tuple[str, str]:
    """Document Intelligence on fixture files: page-cited passages, folder limits enforced."""
    import os

    from openatlas.ev import tools

    try:
        import docx
    except ImportError:
        return _fail("python-docx isn't installed (your install is older than the code). Run: "
                     f"cd '{Config.files.project_root}' && pip install -e .")

    with _ev_sandbox() as d:
        root = d / "docs"
        root.mkdir()
        doc = docx.Document()
        doc.add_paragraph("Doctor fixture. The warranty period is 36 months from the purchase date.")
        doc.save(str(root / "warranty.docx"))
        (root / "notes.md").write_text("# Notes\n\nThe spare key is kept in the blue tin.\n")
        (d / "outside.txt").write_text("secret")
        old = os.environ.get("OPENATLAS_EV_DOC_ROOTS")
        os.environ["OPENATLAS_EV_DOC_ROOTS"] = str(root)
        try:
            a = tools.run("read_document", {"path": "warranty", "question": "how long is the warranty"})
            b = tools.run("read_document", {"path": "notes.md", "question": "where is the spare key"})
            c = tools.run("read_document", {"path": str(d / "outside.txt")})
        finally:
            if old is None:
                os.environ.pop("OPENATLAS_EV_DOC_ROOTS", None)
            else:
                os.environ["OPENATLAS_EV_DOC_ROOTS"] = old
    ok = (a.get("ok") and "36 months" in a["passages"][0]["text"] and b.get("ok") and "blue tin" in b["passages"][0]["text"]
          and not c.get("ok") and "outside the folders" in c.get("error", ""))
    return _pass("Word + Markdown read with cited passages; a file outside the allowed folders is refused") if ok else \
        _fail(f"document reader: {a.get('error') or ''} {b.get('error') or ''} {c}")


def check_ev_voice() -> Tuple[str, str]:
    """Voice pipeline pieces on fixtures: end-of-speech detection, early sentence cut, and the
    voice worker's protocol + latency (with its tone generator standing in for MeloTTS)."""
    import math
    import os
    import struct
    import sys

    from openatlas.ev import voice

    ep = voice.Endpointer()
    ep.vad = None
    step = voice.IN_RATE * voice.FRAME_MS // 1000 * 2
    tone = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 220 * i / voice.IN_RATE)))
                    for i in range(voice.IN_RATE * 600 // 1000))
    audio = b"\x00\x00" * 3200 + tone + b"\x00\x00" * (voice.IN_RATE * (voice.END_SILENCE_MS + 60) // 1000)
    utt = [r["utterance"] for r in (ep.feed(audio[i:i + step]) for i in range(0, len(audio), step)) if r["utterance"]]
    sp = voice.SentenceSplitter()
    first = sp.push("G'day! ") + sp.push("How can I help you today? ")
    env = {k: os.environ.get(k) for k in ("OPENATLAS_EV_TTS_PYTHON", "OPENATLAS_EV_TTS_FAKE")}
    os.environ.update({"OPENATLAS_EV_TTS_PYTHON": sys.executable, "OPENATLAS_EV_TTS_FAKE": "1"})
    try:
        tts = voice.SidecarTTS()
        t0 = time.monotonic()
        pcm = tts.synth("Testing one two three.")
        ms = round((time.monotonic() - t0) * 1000)
        tts.close()
    finally:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    ok = len(utt) == 1 and first and first[0].startswith("G'day") and len(pcm) > 0 and ms < 1500
    if not ok:
        return _fail(f"voice pipeline: utterances={len(utt)} first={first} pcm={len(pcm)} ms={ms}")
    st = voice.status()
    missing = [x for x, v in (("pip install -e '.[voice]'", st["stt"]["available"]),
                              ("openatlas ev voice-setup", st["tts"]["available"])) if not v]
    detail = f"end-of-speech, early sentence and worker protocol verified ({ms} ms per sentence, fake voice)"
    return ("warn", f"{detail}; to talk with E.V: {' and '.join(missing)}") if missing else _pass(detail)


def check_brain3d() -> Tuple[str, str]:
    """The 3D brain builder on a throwaway brain: every link resolves, the node cap holds."""
    from openatlas.kb import store
    from openatlas.utils import knowledge_graph

    with _ev_sandbox():
        store.upsert_many([{"key": f"doctor:{i}", "source": "wikipedia", "title": f"Doctor topic {i}",
                            "text": "fixture " * 30, "tags": ["domain:formal-sciences", "area:logic", "tier:0"]}
                           for i in range(80)])
        g = knowledge_graph.build_brain3d(limit=50)
    ids = {n["id"] for n in g["nodes"]}
    neurons = [n for n in g["nodes"] if n["kind"] == "neuron"]
    ok = len(neurons) == 50 and all(ln["source"] in ids and ln["target"] in ids for ln in g["links"]) \
        and g["meta"]["articles"] == 80
    return _pass(f"{len(g['nodes'])} nodes / {len(g['links'])} links, capped at 50 of 80 neurons") if ok else \
        _fail(f"3D builder: {len(neurons)} neurons, meta {g['meta']}")


def check_ev_persona() -> Tuple[str, str]:
    """E.V's prompt carries all nine traits + guardrails; her simulated mood self-regulates."""
    from openatlas.ev import persona, state

    with _ev_sandbox():
        p = persona.system_prompt(mood={"label": "steady"}, facts=[])
        t = time.time()
        state.appraise("this is broken and useless, ugh", now=t)
        later = state.regulate(state.load(), now=t + 7200)
    ok = all(tr.label in p for tr in persona.TRAITS) and "You are an AI" in p and "Australian" in p \
        and abs(later["valence"] - state.BASELINE["valence"]) < 0.05
    return _pass("9 traits + guardrails in the prompt; mood returns to baseline") if ok else \
        _fail("persona prompt or self-regulation broken")


CHECKS: List[Check] = [
    ("Installation", check_installation),
    ("Schema validator", check_schema_validator),
    ("ToolResult validator", check_toolresult_validator),
    ("Smoke / dry-run runner", check_smoke_runner),
    ("robots.txt guard", check_robots_guard),
    ("Secret / paid-key lint", check_secret_lint),
    ("Scaffolder (isolated round-trip)", check_scaffolder),
    ("Skill linter", check_skill_linter),
    ("Evidence verifier (osint-verify)", check_evidence_verifier),
    ("Network policy", check_net_policy),
    ("Local AI / GPU probe", check_local_ai),
    ("Brain retrievability", check_brain),
    ("Search relevance", check_search_relevance),
    ("Kiwix library", check_library),
    ("E.V approval gate", check_ev_gate),
    ("E.V quality check (claims)", check_ev_qa),
    ("E.V document reader", check_ev_documents),
    ("E.V voice pipeline", check_ev_voice),
    ("E.V persona", check_ev_persona),
    ("3D brain builder", check_brain3d),
]


LIVE_PROBES: List[Tuple[str, str]] = [
    ("DuckDuckGo search", "ddgs"),
    ("GitHub API", "https://api.github.com/users/torvalds"),
    ("Wikipedia API", "https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=OSINT&format=json"),
    ("Reddit JSON", "https://www.reddit.com/user/spez/about.json"),
    ("Hacker News API", "https://hacker-news.firebaseio.com/v0/user/pg.json"),
    ("Stack Exchange API", "https://api.stackexchange.com/2.3/users?inname=skeet&site=stackoverflow&pagesize=1"),
    ("Keybase API", "https://keybase.io/_/api/1.0/user/lookup.json?usernames=chris"),
    ("XposedOrNot", "https://api.xposedornot.com/v1/check-email/test@example.com"),
    ("RDAP", "https://rdap.org/domain/example.com"),
    ("crt.sh", "https://crt.sh/?q=example.com&output=json"),
    ("Wayback CDX", "https://web.archive.org/cdx/search/cdx?url=example.com&limit=1&output=json"),
    ("ip-api", "http://ip-api.com/json/8.8.8.8"),
]


async def _live() -> List[Dict[str, str]]:
    from openatlas.net.client import Net

    out = []
    async with Net(timeout=15) as net:
        async def probe(name: str, url: str) -> Dict[str, str]:
            t0 = time.monotonic()
            if url == "ddgs":
                try:
                    from openatlas.investigate.sources.websearch import _ddg

                    hits = await asyncio.to_thread(_ddg, "OpenStreetMap", 3)
                    ok, detail = bool(hits), f"{len(hits)} results"
                except Exception as exc:
                    ok, detail = False, f"{type(exc).__name__}: {exc}"[:160]
            else:
                r = await net.get(url, max_bytes=64 * 1024)
                ok = r.ok
                detail = r.error or f"HTTP {r.status_code}"
            ms = int((time.monotonic() - t0) * 1000)
            return {"tool": f"live: {name}", "status": "pass" if ok else "warn",
                    "detail": f"{detail} in {ms} ms"}

        out = await asyncio.gather(*(probe(n, u) for n, u in LIVE_PROBES))
    return list(out)


def run_all(live: bool = False) -> Dict[str, Any]:
    checks = []
    for name, fn in CHECKS:
        t0 = time.monotonic()
        try:
            status, detail = fn()
        except Exception as exc:  # a crashing check is a failing check
            status, detail = "fail", f"{type(exc).__name__}: {exc}"
        checks.append({"tool": name, "status": status, "detail": detail,
                       "ms": int((time.monotonic() - t0) * 1000)})
    if live:
        checks += asyncio.run(_live())
    return {"ok": all(c["status"] != "fail" for c in checks), "checks": checks,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
