"""``forge doctor``: automatically verify every tool the skills depend on.

Each check feeds the tool a known-good AND a known-bad fixture and confirms it tells them
apart - so a tool that silently stopped working (e.g. a validator that passes everything)
is caught. Nothing here patches globals, so it is safe to run inside the live server.

``live=True`` additionally probes each public data source once from *your* network and
reports which ones answer (this is the only part that uses the internet).
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import httpx

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
    from openatlas.utils.secret_lint import default_target, iter_files, scan_path, scan_text

    planted = scan_text('api_key = "' + "sk-" + "a1b2c3d4" * 4 + '"')
    clean = scan_text("def ok():\n    return 'nothing secret here'\n")
    # Always the installed package (absolute path): the result must not depend on the folder
    # you run `openatlas doctor` from, and must never scan a virtualenv's site-packages.
    target = default_target()
    n_files = len(iter_files(target))
    repo = scan_path(target)
    if planted and not clean and n_files and not repo:
        return _pass(f"planted key caught; clean text passes; {n_files} source files clean")
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

    real = [s for s in registry.list_skills() if not s["lint_ok"]]
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "Bad_Skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: Bad_Skill\ndescription: x\n---\n# nothing\n")
        rejected = not linter.lint_skill(str(bad), run_commands=False)["ok"]
    if not real and rejected:
        return _pass(f"{len(registry.list_skills())} project skills valid; broken skill rejected")
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

    if not ollama_client.ping():
        return "warn", "local AI (Ollama) offline - optional; start it with `ollama serve`"
    rep = ollama_client.gpu_report()
    cpu = [m["model"] for m in rep["models"] if not m["on_gpu"]]
    if detect().gpus and cpu:
        return "warn", f"GPU present but {', '.join(cpu)} running on CPU - check GPU drivers"
    return _pass(f"online; profile models ready ({len(rep['models'])} loaded)")


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
    if not found or nonsense:
        return _fail(f"self-test: fixture found={found}, nonsense query returned {len(nonsense)} hits")

    with store.connect() as con:
        n = con.execute("SELECT COUNT(*) FROM documents WHERE source='wikipedia'").fetchone()[0]
        row = con.execute("SELECT title, key FROM documents WHERE source='wikipedia' "
                          "ORDER BY RANDOM() LIMIT 1").fetchone()
    if not row:
        return _pass("store + search self-test ok; your brain has 0 articles yet - grow it with "
                     "`openatlas kb ingest` or 'Grow the brain'")
    hits = retrieve.search(row["title"], k=5, use_vectors=False)
    if any(h["key"] == row["key"] for h in hits):
        return _pass(f"self-test ok; {n} articles, random '{row['title']}' retrievable in top 5")
    return _fail(f"your brain: '{row['title']}' not found in top 5 for its own title")


CHECKS: List[Check] = [
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
