# OpenAtlas 🗺️

**A fully free / open-source / local OSINT toolkit — a key-free reimplementation of
[OAtlas](https://github.com/FauvidoTechnologies/open-atlas)'s AA (Aggregate & Analyze)
workflow.**

OpenAtlas gives an investigator a single entry point to **19 engines / 44 functions**
across social media, email & identity, geolocation, image & binary analysis, web &
domain, code & secrets, breach, and network reconnaissance — with **every paid API key
replaced by a free, keyless, or local substitute**. There is nowhere to put a paid key,
and none is ever read.

> ⚖️ **Public data only. Respects robots.txt. No login/CAPTCHA/paywall bypass.**
> See [ETHICS.md](ETHICS.md) — these rules are enforced in code.

---

## Why "free/local"? The substitution map

| OAtlas needed (paid/key) | OpenAtlas uses instead (free) |
|---|---|
| OpenAI / VertexAI | **Ollama** (local, OpenAI-compatible) for all LLM/vision/reasoning |
| Perplexity | **DuckDuckGo** (`ddgs`) + optional local-LLM summarisation |
| Hunter.io | **Holehe** + email permutation + DNS/MX verification |
| HIBP (paid) / OathNet | **HIBP Pwned Passwords** (k-anonymity) + **XposedOrNot** (keyless) |
| isgen.ai | **Local Hugging Face** deepfake model + C2PA/EXIF analysis |
| Picarta / IPinfo (paid) | **EXIF GPS + Nominatim** geocode; **ip-api / ipapi.co / RIPEstat** |
| username APIs | **WhatsMyName** OSS dataset (bundled) |

`python3 openatlas.py --show-api-services` prints the full list and proves every backend
is keyless/local.

## Install

```bash
git clone https://github.com/voidless026-design/Map.git openatlas
cd openatlas
poetry install                       # core (no GPU needed)
# optional groups, install what you need:
poetry install --with search,email,image,browser,web
poetry install --with ml             # heavy, local deepfake/DeepFace models
make fetch-data                      # download the WhatsMyName username dataset
# optional Rust-accelerated binary carving:
make maturin-develop
```

For LLM-powered functions, run a local **Ollama**:

```bash
ollama serve &
ollama pull llama3.1:8b      # text/reasoning
ollama pull llava            # vision, for image geolocation
```

Everything else works without Ollama — those functions **degrade gracefully** with a
clear "backend unavailable" message instead of crashing.

## Usage

```bash
python3 openatlas.py --show-all-functions        # list every engine/function
python3 openatlas.py --show-api-services         # prove backends are free/local
python3 openatlas.py -f verify_email_address -v  # run a function (interactive args)
python3 openatlas.py -f geolocate_using_LLMs -o  # -o = use the local Ollama LLM
python3 openatlas.py -f check_usernames fetch_about   # chain multiple functions
python3 openatlas.py --snapshot-txt example.com  # download robots.txt/security.txt/...
python3 openatlas.py --verify                    # self-verify all 44 functions
python3 openatlas.py --start-web-server          # optional Streamlit UI
```

Every run is logged to a database (SQLite by default; MySQL/PostgreSQL optional) so you
can rebuild reports and track investigation history.

## Engines (AA mode)

Social media (Reddit ×2, Instagram) · Email & identity (verify, professional-email
finder, breach checks) · Geolocation (EXIF + local vision LLM + OSM) · Image & binary
(EXIF/C2PA, OCR, face match, firmware/strings carving) · Web & domain (get-pages,
hyperlink extract, LLM browser automation) · Code & secrets (GitHub profile/repos +
public-repo secret scan) · Breach (keyless) · Network (authorization-gated port scan).

Full details: `python3 openatlas.py --show-all-functions`.

## The two skills (`.claude/skills/`)

OpenAtlas ships two Claude Code skills that remove the manual re-checking an investigator
does after an AI produces an output:

- **`skill-forge`** — *generates a new OSINT function/engine and then verifies it*
  (import/registration, schema-lint, mocked dry-run returning a valid `ToolResult`,
  public-only/robots + no-secrets guard, and pytest). It refuses to call a tool "done"
  while any check fails. `python -m openatlas.utils.forge new-engine ...` then
  `python -m openatlas.utils.forge verify <fn>`.
- **`osint-verify`** — *independently verifies findings* an AI produced (resolve a
  claimed profile URL, cross-check geolocation vs. EXIF + OSM, confirm email MX,
  second-source a breach hit) and emits a corroboration table, flagging anything it
  can't confirm rather than asserting it. `python -m openatlas.utils.verify_findings ...`.

## Architecture

```
Input → pick function(s) → engine executes (free/local backend) → ToolResult
     → logged to DB → optionally chain the next function → report
```

- `openatlas/core/registry.py` — `ToolRegistry` / `BaseTool` / `ToolSpec` / `ToolResult`.
- `openatlas/methods/methods.yaml` — the validated function catalogue.
- `openatlas/llm/ollama_client.py` — the only LLM path (local Ollama).
- `openatlas/utils/robots.py` — the robots.txt guard every scraper routes through.
- `openatlas/reasoning/loop.py` — ATLAS-inspired plan→execute→check→repair (AA mode).
- `openatlas/browser/engine.py` — PyBA-style Playwright automation, reasoning via Ollama.

## Testing

```bash
make test     # pytest, all network/LLM mocked — never touches the internet
make verify   # run the self-verifier over all 44 functions
make lint     # ruff + secret/paid-key lint
```

## Credits & licences

Independent work inspired by OAtlas, PyBA, OpenJarvis (Apache-2.0) and ATLAS (AGPL-3.0);
uses the WhatsMyName dataset and optionally Holehe. See [NOTICE](NOTICE). MIT licensed.

> **Sandbox note:** in a restricted cloud container the outbound proxy may block most
> external hosts, so live lookups won't run there — run OpenAtlas on your own machine
> (with network + optional Ollama) to exercise the engines end to end.
