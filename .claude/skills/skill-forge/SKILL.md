---
name: skill-forge
description: >-
  Generate a NEW OpenAtlas OSINT function/engine (or an agentskills.io skill wrapping
  it) AND automatically verify it before it is trusted. Use whenever the user wants to
  "add a new OSINT function", "scaffold an engine", "wrap <some free API/tool> as an
  OpenAtlas tool", "create a skill for <task>", or "make a tool that does <X>". The
  skill scaffolds the code + methods.yaml entry + registry hook + a pytest, then runs a
  five-part verification (import/registration, schema-lint, mocked dry-run returning a
  valid ToolResult, public-only/robots + no-secrets guard, and pytest) and reports
  pass/fail. It refuses to declare the tool "done" while any check fails.
license: MIT
metadata:
  project: OpenAtlas
  produces: [python-engine, methods.yaml-entry, pytest, verification-report]
---

# skill-forge — generate a tool, then prove it works

`skill-forge` exists because a generated OSINT function you can't trust is worse than
no function: it produces outputs an investigator then has to re-check by hand. This
skill removes that manual re-checking by baking a **verification step** into every tool
it creates. It does two things in one pass: **(1) generate** a new engine/function, and
**(2) verify** it against a fixed contract.

## When to trigger

Trigger this skill when the request is to create or extend an OSINT capability. Concrete
examples:

- "Add a function that looks up a domain's DNS TXT records." → new engine
  `dns_txt_lookup` under a `DnsEngine`.
- "Wrap the free crt.sh certificate-transparency API as an OpenAtlas tool." → new
  `CertTransparencyEngine.search_crtsh`.
- "I want a tool that checks whether a phone number is valid using the local
  `phonenumbers` library." → new `PhoneEngine.validate_number`.
- "Scaffold an engine for Mastodon public profile lookups." → new `MastodonEngine`.
- "Create a skill that summarizes a target's breach exposure." → composite skill that
  chains existing engines and is verified end-to-end.

Do **not** trigger it for: running an existing function (use the CLI), fixing a bug in an
existing engine (edit directly), or anything that requires a paid API key (OpenAtlas
policy forbids it — propose a free/local substitute instead).

## Inputs to collect first

1. **Capability**: what the function does, in one sentence.
2. **Backend**: which free/keyless/local source it uses (public API, local library,
   Ollama). If the user names a paid service, map it to a free substitute and confirm.
3. **Signature**: function name (snake_case), arguments with `type`/`required`/`description`.
4. **Network shape**: does it hit the network? does it scrape web pages (→ must be
   robots-gated)? does it need Ollama?

## Step 1 — Generate

Create the files, following the existing engine pattern (see
`openatlas/tools/ip_lookups.py` for a clean template):

1. **Engine module** `openatlas/tools/<engine>.py`:
   - a `BaseTool` subclass decorated with `@ToolRegistry.register("<common-name>")`;
   - `abbrev`, `description`, and a `specs` dict of `ToolSpec` objects (set
     `network`, `scrapes_web`, `needs_llm`, `backend` honestly);
   - each function is a `@staticmethod` returning a `ToolResult`. Use
     `openatlas.utils.http.api_get_json` for public APIs and
     `openatlas.utils.http.scrape_get` for web pages (it enforces robots.txt). On
     failure return `ToolResult.failure(...)`; when a backend is unreachable return
     `ToolResult.unavailable(...)` so it degrades instead of crashing.
   - **Never** send `Authorization`/`Cookie` headers, log in, solve CAPTCHAs, or bypass
     paywalls. **Never** hardcode a key.
2. **Register the import** in `openatlas/tools/__init__.py`.
3. **Document it** in `openatlas/methods/methods.yaml`: an engine block with
   `common_name`, `abbrev`, `description`, and a `functions` map giving every argument a
   `type`, `required`, and `description`.
4. **Write a pytest** `tests/test_<engine>.py` that mocks the network
   (`openatlas.utils.http`) / Ollama and asserts a well-formed `ToolResult`.

Use the scaffolder to do the mechanical parts:

```bash
python -m openatlas.utils.forge new-engine \
  --engine <EngineClass> --common-name <common-name> --abbrev <abbr> \
  --function <func_name> --backend "<free backend>" [--scrapes-web] [--needs-llm]
```

## Step 2 — Verify (the differentiator)

Run the verification harness. It performs five checks and returns a JSON report; the
tool is only "done" when every check passes.

```bash
python -m openatlas.utils.forge verify <func_name>
# or, over everything:
python3 openatlas.py --verify
```

The five checks (implemented in `openatlas/utils/smoke_run.py`):

1. **registered / callable** — the function is importable and present in
   `ToolRegistry`, with a `ToolSpec`.
2. **documented** — it appears in `methods.yaml` with a valid, typed argument schema
   (validated by `openatlas/utils/schema_validate.py`).
3. **returns_toolresult** — a **mocked dry-run** (network + Ollama patched off) returns
   a well-formed `ToolResult` whose `content` is JSON-serialisable and whose failed
   results carry an `error`. Proves the function never hard-crashes and degrades
   gracefully offline.
4. **public-only / no-secrets guard** — if the function's own source calls
   `scrape_get`, its spec must declare `scrapes_web=True` (robots enforced); the source
   must not use auth headers/cookies; and the secret lint
   (`openatlas/utils/secret_lint.py`) must find no hardcoded key or paid-key literal.
5. **pytest** — `pytest -k <func_name>` is green.

Then finish with:

```bash
python -m openatlas.utils.secret_lint openatlas/tools/<engine>.py   # must be clean
ruff check openatlas/tools/<engine>.py
```

Report the verification JSON back to the user. If any check fails, fix the generated
code and re-run — do **not** report success on a failing check.

## Tools this skill needs (and why)

These are the tools that make the output trustworthy; all ship with OpenAtlas:

| Tool | Module | Why it improves the output |
|---|---|---|
| Schema validator | `openatlas/utils/schema_validate.py` | Guarantees the new function is documented with typed args and matches the registry — no silent drift. |
| Smoke/dry-run runner | `openatlas/utils/smoke_run.py` | Executes the function with mocked network/LLM and asserts a valid `ToolResult` — catches crashes and bad return shapes without touching the internet. |
| ToolResult validator | `openatlas/utils/schema_validate.py:validate_tool_result` | Enforces the uniform result envelope so DB logging and reports never break. |
| robots/ToS guard | `openatlas/utils/robots.py` | Confirms scrapers are robots-gated and lets the tool download robots.txt/security.txt for the record. |
| Ollama probe | `openatlas/llm/ollama_client.py:ping/available` | Lets the tool detect a missing local LLM and degrade gracefully instead of erroring. |
| Secret/PII lint | `openatlas/utils/secret_lint.py` | Blocks any hardcoded credential or paid-API-key literal from entering the codebase. |
| Scaffolder | `openatlas/utils/forge.py` | Writes the boilerplate (engine, methods.yaml entry, pytest) consistently. |

## Definition of done

- New engine registered and listed by `python3 openatlas.py --show-all-functions`.
- `python3 openatlas.py --verify <func_name>` returns `ok: true` for all five checks.
- `methods.yaml` validates; secret lint clean; ruff clean; pytest green.
- No paid key introduced; scrapers robots-gated; failures degrade, never crash.
