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

## Testing
`make test` (mocked, offline), `make verify` (self-verifier), `make lint`. Tests must
never hit the network — mock `openatlas.utils.http` / `openatlas.llm.ollama_client`.

## LLM
The only LLM path is local Ollama via `openatlas/llm/ollama_client.py` (OpenAI-compatible).
Configure with `OLLAMA_HOST`. Code must work when Ollama is absent.
