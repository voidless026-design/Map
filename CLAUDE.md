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
  - The package scan (`package=True`, used by the doctor) skips repository leftovers inside the package (`tests/`, nested checkouts) and reports them.

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
- OpenAtlas skills carry `metadata: project: OpenAtlas`, or mention `openatlas`, and must meet the house rules.
- Third-party skills in `.claude/skills` are linted against the Agent Skills spec only.

## v2 layout
- `openatlas/investigate/` - evidence pipeline; new sources use `@source(...)` in
  `investigate/sources/` and the bounded `openatlas.net.client.Net` (pages: `page=True`
  => robots-gated, data brokers skipped). Return `SourceResult`; set `ok=False` + `error`
  on network failure - never report "0 found" when nothing answered.
- `openatlas/kb/` - the brain (SQLite FTS5 in `OPENATLAS_DATA_DIR/brain`).
  - `retrieve.py` is search-engine style: a query parser, the title/alias index (`titles`), coverage, and a relevance gate. Every hit carries `why`.
    - Any ranking change must keep `openatlas kb eval --fixture` passing. The doctor also requires the legacy ranker to fail.
  - `library.py` handles Kiwix ZIM books: the OPDS catalog, Range-resume downloads, SHA-256 verification, duplicate/update rules, and libzim ingest.
    - Downloads run `MAX_PARALLEL` (2) at a time, one thread per book with its own stop event (`schedule()` / `control()`); pause/cancel act at once and hand the slot on. Ingest has its own thread. Worker threads run in a copied context so `store.use_path` follows them.
    - `kiwix.py` runs kiwix-serve on loopback, proxied at `/kiwix`.
    - Only https `*.kiwix.org` URLs are accepted.
    - Kiwix's `q=` search matches titles and descriptions only, never file names. Look up books by name through `find_books` / `resolve`, which page through the catalog and match file names locally.
- User-facing commands in docs and skills have no `<placeholders>`: people paste them literally. Use real examples (`pause 1`). `openatlas kb where` prints ready-to-paste data-dir lines.
    - Tests use `library.TRANSPORT` = `httpx.MockTransport`, plus real ZIMs built with `libzim.writer`.
- `openatlas/utils/knowledge_graph.py` + `webserver/visualizer/atsmatrix.html` (ATSMATRIX fork) -
  case graphs (`/viz/<case>`) and the brain graph (`/viz/brain`, `openatlas kb graph`). Feed the
  visualizer new graph builders.
  - The visualizer is tuned for older GPUs (batched edges, sprite glow instead of `shadowBlur`, an fps
    cap, adaptive quality) and has a small Customize panel (localStorage `oa-brain2d`). Keep per-frame
    work batched, and keep the default look unchanged when you edit it.
  - There is no 3D brain any more (removed at the user's request: too slow on their GTX 770).
- `openatlas/reasoning/loop.py` (ATLAS-inspired) - `plan_case` (Auto-plan / `openatlas plan`: proposes
  sources, a human presses Run) and `check_case` (post-case check + one repair round). Local AI when
  available, deterministic heuristic otherwise.
- `openatlas/web/` - FastAPI + no-build SPA (`openatlas serve`, loopback only).
  - The home page is E.V's chat (`static/ev.js`). `web/ev_routes.py` has the `/api/ev/*` endpoints and the `/ws/ev/voice` WebSocket.
- `openatlas/ev/` - E.V, the local AI companion.
  - `persona.py` holds the nine trait dials and the fixed guardrails. `state.py` is her simulated mood and trust, with self-regulation. `memory.py` handles context continuity.
  - `agent.py` runs the streaming turn: Ollama tool calls, a keyword router when the model can't call tools, and an offline fallback. `tools.py` has the registry, approval gate, ethics screen and risk appraisal.
  - `skills/*` are the nine skills. Only `read` tools auto-run; `network`, `write` and `command` tools always go through `tools.decide`.
  - `voice.py` handles endpointing, sentence streaming and barge-in. `ev.js` shows every spoken sentence as a subtitle (from `audio_start` / `say`) while it plays. `tts_worker.py` is MeloTTS EN-AU in its own py3.11 venv (`openatlas ev voice-setup`).
  - New E.V skills are generated with `forge new-skill`, and the doctor verifies their tools.
  - `skills/engineering.py` (adapted from everything-claude-code) holds `review_code`, `verify_project`, `learn_pattern`, `checkpoint`, `plan_feature` and `eval_answers`.
    - Review reads only E.V's allowed folders.
    - Verify runs a fixed command list per project type, never arbitrary shell. Tests swap `engineering.RUNNER`.
    - A checkpoint stores the last message id in kv `checkpoint:<conv>`; `memory.recent_for_model` sends only newer messages.
- `openatlas/llm/ollama_client.py` always resolves the model against `/api/tags` (`resolve_model` / `diagnose`). Never hard-code a model name that might not be pulled.
- `openatlas/cli.py` - `investigate|run|catalog|serve|cases|kb|doctor`; `openatlas/catalog.py`
  gives every action a human title + kebab slug (no underscores in titles).
- `openatlas/runtime/` - resource profiles, LLM gate, memory guard. Any heavy model load
  goes through `runtime.limits` (cached, gated) - never load per call.

## Working on OpenAtlas with Claude Code
Adapted from everything-claude-code (MIT); see `.claude/ECC-NOTICE.md`.
- Agents in `.claude/agents/`:
  - `planner` and `architect` before multi-file changes;
  - `tdd-guide` for features and bugs (failing test first);
  - `code-reviewer` after every change, plus `security-reviewer` when the change touches input, paths, network, subprocesses, the web API or E.V tools;
  - `build-error-resolver` when a gate is red;
  - `e2e-runner` for GUI changes;
  - `refactor-cleaner` and `doc-updater` on request.
- Commands in `.claude/commands/`, all prefixed `oa-` to avoid clashing with built-ins: `/oa-plan`, `/oa-tdd`, `/oa-verify` (the exact CI gate), `/oa-review`, `/oa-checkpoint`, `/oa-learn`, `/oa-eval`, `/oa-orchestrate`, `/oa-build-fix`, `/oa-e2e`, `/oa-test-coverage`, `/oa-refactor-clean`, `/oa-update-docs`.
- Rules:
  - Plan first for multi-file work.
  - Write the failing test first.
  - Review before commit.
  - Not done until every `/oa-verify` gate passes.
  - Never skip or loosen a test to get green.
  - Save a lesson (`/oa-learn`) only after the user says yes.
- `tests/test_claude_dev_files.py` lints these files:
  - frontmatter present;
  - a source line;
  - no npm/TypeScript leftovers;
  - no paid services;
  - every documented `openatlas` command passes `--help`.

## Testing
`make test` (mocked, offline), `make verify` (self-verifier), `make lint`, `make doctor`,
`make skills`. Tests must never hit the network: `tests/conftest.py` blocks httpx and
requests; use the `mock_http` fixture (v2 client) or mock `openatlas.utils.http`.

## LLM
The only LLM path is local Ollama via `openatlas/llm/ollama_client.py` (native API, gated).
Configure with `OLLAMA_HOST`. Code must work when Ollama is absent.
