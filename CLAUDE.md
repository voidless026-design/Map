# OpenAtlas — notes for Claude / contributors

## What this is
A free/local/no-key OSINT toolkit reimplementing OAtlas's AA mode. **Never introduce a
paid API key or a paid backend.** Map any paid dependency to a free/keyless/local one.

## Non-negotiable rules (also enforced in code)
- Public, unauthenticated data only. No login, cookies, CAPTCHA solving, or paywall bypass.
- All web-page scraping must go through `openatlas.utils.http.scrape_get` (robots-gated).
  Use `api_get_json` for public APIs. Never add `Authorization`/`Cookie` headers.
- Active network scanning stays authorization-gated (`--authorized-target`).
- Stealer-log retrieval stays disabled. Only defensive breach-existence checks.
- No hardcoded secrets. `python -m openatlas.utils.secret_lint openatlas` must be clean.

## Adding a function
Use the `skill-forge` skill / scaffolder:
```bash
python -m openatlas.utils.forge new-engine --engine XEngine --common-name x --abbrev xE \
  --function do_x --backend "<free backend>" [--network] [--scrapes-web] [--needs-llm]
python -m openatlas.utils.forge verify do_x     # must be ok:true
```
Then implement the body, keep `methods.yaml` in sync (it's validated), and add/keep a
pytest. Functions must return a `ToolResult`; use `ToolResult.unavailable(...)` when a
backend (e.g. Ollama) is unreachable so it degrades instead of crashing.

## Adding a skill
```bash
python -m openatlas.utils.forge new-skill --name my-skill --description "..." \
  --trigger "..." --trigger "..." --trigger "..." --command "openatlas catalog"
```
`new-skill` lints the result immediately (spec frontmatter, >=3 triggers, Verification +
Tools sections, every documented `openatlas ...` command must pass `--help`).
`python -m openatlas.utils.forge verify-skill --all` and `python -m openatlas.utils.forge doctor`
must both pass (CI runs them).

## v2 layout
- `openatlas/investigate/` - evidence pipeline; new sources use `@source(...)` in
  `investigate/sources/` and the bounded `openatlas.net.client.Net` (pages: `page=True`
  => robots-gated, data brokers skipped). Return `SourceResult`; set `ok=False` + `error`
  on network failure - never report "0 found" when nothing answered.
- `openatlas/kb/` - the brain (SQLite FTS5 in `OPENATLAS_DATA_DIR/brain`).
- `openatlas/utils/knowledge_graph.py` + `webserver/visualizer/atsmatrix.html` (ATSMATRIX fork) -
  case graphs (`/viz/<case>`) and the brain graph (`/viz/brain`, `openatlas kb graph`). Feed the
  visualizer new graph builders; don't change the visualizer file itself.
- `openatlas/web/` - FastAPI + no-build SPA (`openatlas serve`, loopback only).
- `openatlas/cli.py` - `investigate|run|catalog|serve|cases|kb|doctor`; `openatlas/catalog.py`
  gives every action a human title + kebab slug (no underscores in titles).
- `openatlas/runtime/` - resource profiles, LLM gate, memory guard. Any heavy model load
  goes through `runtime.limits` (cached, gated) - never load per call.

## Testing
`make test` (mocked, offline), `make verify` (self-verifier), `make lint`, `make doctor`,
`make skills`. Tests must never hit the network: `tests/conftest.py` blocks httpx and
requests; use the `mock_http` fixture (v2 client) or mock `openatlas.utils.http`.

## LLM
The only LLM path is local Ollama via `openatlas/llm/ollama_client.py` (native API, gated).
Configure with `OLLAMA_HOST`. Code must work when Ollama is absent.
