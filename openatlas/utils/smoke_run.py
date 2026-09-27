"""Smoke-test / verification harness for OpenAtlas engines.

Used directly by the ``skill-forge`` skill's *verification step*. Given a function
name, it:

1. Confirms the function is importable and registered in the ToolRegistry.
2. Confirms it is documented in ``methods.yaml`` with a valid arg schema.
3. Dry-runs it with synthetic/mock inputs (network mocked) and asserts the return
   value is a well-formed :class:`ToolResult`.
4. Confirms scraping functions declare ``scrapes_web=True`` (=> robots enforced) and
   don't send auth headers.
5. Runs the secret lint over the engine's source file.

It returns a structured report and a boolean ``ok``. Nothing here needs network,
Ollama, or a GPU - degraded results still count as well-formed.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Optional
from unittest import mock

from openatlas.core.registry import ToolRegistry, ToolResult, ToolSpec, load_all_engines
from openatlas.utils import secret_lint
from openatlas.utils.schema_validate import validate_methods_yaml, validate_tool_result

# Synthetic inputs by argument name (best-effort; falls back to type defaults).
_MOCK_BY_NAME = {
    "email": "test@example.com",
    "username": "octocat",
    "url": "https://example.com",
    "urls": "https://example.com,https://example.org",
    "ipaddress": "8.8.8.8",
    "ip": "8.8.8.8",
    "asn_number": "15169",
    "domain_name": "example.com",
    "first_name": "Jane",
    "last_name": "Doe",
    "query": "example",
    "search_request": "example",
    "image_path": "/nonexistent/mock.jpg",
    "image_url": "https://example.com/mock.jpg",
    "prompt": "list the page title",
}
_MOCK_BY_TYPE = {
    "string": "mock",
    "integer": 1,
    "number": 1.0,
    "boolean": False,
    "array": [],
    "object": {},
}


def _mock_args(spec: ToolSpec) -> Dict[str, Any]:
    args: Dict[str, Any] = {}
    for name, meta in spec.parameters.items():
        if not meta.get("required", False):
            continue
        if name in _MOCK_BY_NAME:
            args[name] = _MOCK_BY_NAME[name]
        else:
            args[name] = _MOCK_BY_TYPE.get(meta.get("type", "string"), "mock")
    return args


def _engine_source(engine: type) -> Optional[str]:
    try:
        return inspect.getsourcefile(engine)
    except (TypeError, OSError):  # pragma: no cover
        return None


def _function_source(fn: Any) -> Optional[str]:
    """Return the source text of a single function (best-effort)."""
    try:
        return inspect.getsource(fn)
    except (TypeError, OSError):  # pragma: no cover
        return None


# Real request-auth markers (header keys / cookie usage), not prose mentions.
_AUTH_HEADER_MARKERS = [
    '"Authorization"', "'Authorization'", "Authorization:",
    '"Cookie"', "'Cookie'", "Cookie:",
    "set_cookie", "cookies=", "add_cookies",
]


def verify_function(function_name: str, *, run: bool = True,
                    engine_name: Optional[str] = None) -> Dict[str, Any]:
    """Verify a single function end-to-end. Returns a report dict.

    ``engine_name`` disambiguates functions that share a name across engines
    (e.g. Reddit's and GitHub's ``fetch_about``)."""
    load_all_engines()
    report: Dict[str, Any] = {"function": function_name, "checks": [], "ok": True}
    if engine_name:
        report["engine"] = engine_name

    def _check(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            report["ok"] = False

    # 1. Registered & importable
    engine = (next((e for e in ToolRegistry.engines().values() if e.__name__ == engine_name), None)
              if engine_name else ToolRegistry.engine_for_function(function_name))
    _check("registered", engine is not None, "" if engine else "not in ToolRegistry")
    if engine is None:
        return report

    spec = engine.specs.get(function_name)
    _check("has_spec", spec is not None, "" if spec else "no ToolSpec")
    fn = engine.get_callable(function_name)
    _check("callable", callable(fn), "" if callable(fn) else "attribute not callable")

    # 2. Documented with valid schema
    yaml_report = validate_methods_yaml(check_registry=False)
    doc_errs = [e for e in yaml_report["errors"] if function_name in e]
    _check("documented", not doc_errs, "; ".join(doc_errs))

    # 4. Ethics metadata sanity - inspect THIS function's own source, not the module.
    if spec is not None and callable(fn):
        text = _function_source(fn)
        if text is not None:
            uses_scrape = "scrape_get" in text
            if uses_scrape:
                _check(
                    "robots_gated",
                    spec.scrapes_web,
                    "uses scrape_get but spec.scrapes_web is False" if not spec.scrapes_web else "",
                )
            # No auth headers / cookies in a public-data-only tool. Match real header
            # usage (quoted keys / header-style assignments), not prose like "authorization".
            bad = [p for p in _AUTH_HEADER_MARKERS if p in text]
            _check("no_auth_headers", not bad, f"found {bad}" if bad else "")
            # 5. Secret lint over the function body.
            findings = secret_lint.scan_text(text, function_name)
            _check("no_secrets", not findings, f"{len(findings)} finding(s)" if findings else "")

    # 3. Dry-run with mocked network
    if run and spec is not None and callable(fn):
        args = _mock_args(spec)
        result = _dry_run(fn, args)
        vr = validate_tool_result(result)
        _check("returns_toolresult", vr["ok"], "; ".join(vr.get("errors", [])))
        if isinstance(result, ToolResult):
            report["sample_result"] = {
                "success": result.success,
                "degraded": result.metadata.get("degraded", False),
                "error": result.error,
            }

    return report


def _dry_run(fn: Any, args: Dict[str, Any]) -> Any:
    """Call ``fn(**args)`` with all outbound HTTP mocked to a benign 404-ish response."""

    class _Resp:
        status_code = 404
        text = ""
        content = b""
        headers: Dict[str, str] = {}

        def json(self) -> Dict[str, Any]:
            return {}

    def _fake_get(*a: Any, **k: Any) -> _Resp:
        return _Resp()

    import httpx

    patches = [
        # v2 async client: every request gets a 404 (no network in a dry run).
        mock.patch("openatlas.net.client.TRANSPORT",
                   new=httpx.MockTransport(lambda req: httpx.Response(404, content=b""))),
        mock.patch("openatlas.utils.http.api_get", side_effect=_fake_get),
        mock.patch("openatlas.utils.http.api_get_json", return_value=None),
        mock.patch("openatlas.utils.http.scrape_get", return_value=None),
        mock.patch("openatlas.llm.ollama_client.available", return_value=False),
        mock.patch("openatlas.llm.ollama_client.ping", return_value=False),
        mock.patch("requests.get", side_effect=_fake_get),
    ]
    started = []
    try:
        for p in patches:
            try:
                p.start()
                started.append(p)
            except Exception:  # pragma: no cover - target may not exist
                pass
        try:
            return fn(**args)
        except Exception as exc:  # a dry-run crash is itself a failed check
            return ToolResult.failure(getattr(fn, "__name__", "?"), f"raised {type(exc).__name__}: {exc}")
    finally:
        for p in started:
            p.stop()


def verify_engine(common_name: str) -> Dict[str, Any]:
    """Verify every function of one engine by common_name."""
    load_all_engines()
    engine = ToolRegistry.engines().get(common_name)
    if engine is None:
        return {"engine": common_name, "ok": False, "error": "engine not registered"}
    reports = [verify_function(fn) for fn in engine.function_names()]
    return {"engine": common_name, "ok": all(r["ok"] for r in reports), "functions": reports}


def verify_all() -> Dict[str, Any]:
    """Verify every registered function. Returns an aggregate report."""
    load_all_engines()
    # Iterate engines x functions so same-named functions in different engines are all checked.
    reports = [verify_function(fn, engine_name=engine.__name__)
               for engine in ToolRegistry.engines().values() for fn in engine.function_names()]
    return {
        "ok": all(r["ok"] for r in reports),
        "total": len(reports),
        "failed": [f"{r.get('engine')}.{r['function']}" for r in reports if not r["ok"]],
        "functions": reports,
    }
