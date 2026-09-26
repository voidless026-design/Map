# Adding new tools to OpenAtlas

OpenAtlas keeps OAtlas's "plug-and-play" philosophy: a new function is a `@staticmethod`
on a `BaseTool` subclass, registered once and documented once. The `skill-forge` skill
automates all of this and then **verifies** the result.

## The five touch-points

1. **Engine module** — `openatlas/tools/<engine>.py`: a `BaseTool` subclass decorated
   with `@ToolRegistry.register("<common-name>")`, exposing a `specs` dict of `ToolSpec`
   and one `@staticmethod` per function returning a `ToolResult`.
2. **Import** — add the module to `openatlas/tools/__init__.py`.
3. **Schema** — add an engine block to `openatlas/methods/methods.yaml` (every arg needs
   `type`, `required`, `description`). It is validated against the registry.
4. **Description** — surfaced automatically from the `ToolSpec` by
   `openatlas/utils/tool_descriptions.py`.
5. **Test** — `tests/test_<engine>.py` with network/LLM mocked.

## Scaffold + verify

```bash
python -m openatlas.utils.forge new-engine \
  --engine DnsEngine --common-name dns-lookups --abbrev dnsE \
  --function txt_records --backend "dns (local resolver)" --network
# implement the body, then:
python -m openatlas.utils.forge verify txt_records   # -> ok: true
```

## Rules (see CLAUDE.md / ETHICS.md)
- Free/keyless/local backends only; never a paid key.
- Web-page scraping via `scrape_get` (robots-gated); public APIs via `api_get_json`.
- Return `ToolResult.unavailable(...)` when a backend is down; never crash.
- No auth headers, no CAPTCHA/paywall bypass.
