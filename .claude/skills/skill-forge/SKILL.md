---
name: skill-forge
description: >-
  Generate a new OpenAtlas capability - an OSINT engine/function OR an agent skill
  (SKILL.md) - and automatically verify it before anyone trusts it. Use when the user
  says "add a function that...", "wrap <free API> as a tool", "scaffold an engine",
  "create a skill for <task>", "turn this workflow into a skill", or "check that my
  skills still work". Engines get code + methods.yaml + registry hook + pytest, then a
  7-check verification (registered, spec, callable, documented, robots-gated, no
  auth/secrets, mocked dry-run returns a valid ToolResult). Skills are generated as a
  draft, linted immediately (spec frontmatter, trigger examples, verification and tools
  sections, every documented command run), and only promoted into .claude/skills once
  they pass. Both finish with `doctor`, which proves the verifying tools themselves work
  on known-good/known-bad fixtures. Nothing is reported done while a check fails.
  Free/local backends only - never a paid key.
license: MIT
metadata:
  project: OpenAtlas
  produces: [python-engine, methods.yaml-entry, pytest, skill-md, verification-report]
---

# skill-forge - generate it, then prove it works

The manual task this removes: an AI hands you a new tool or a new skill and you then
check by hand whether it imports, whether its docs match, whether the commands it tells
you to run even exist, and whether it quietly needs a paid key or scrapes behind a
login. skill-forge does the **generate** step and the **verify** step in one pass and
refuses to call anything finished until the checks are green.

## When to trigger

- "Add a function that looks up a domain's DNS TXT records." -> `new-engine`
- "Wrap the free crt.sh certificate-transparency API as an OpenAtlas tool." -> `new-engine`
- "I want a tool that validates phone numbers offline with `phonenumbers`." -> `new-engine`
- "Create a skill that investigates a username end-to-end." -> `new-skill`
- "Turn my 'curate the brain' routine into a reusable skill." -> `new-skill`
- "Do all our skills and their tools still work?" -> `verify-skill --all` + `doctor`

Do **not** trigger it to *run* an existing function (use `openatlas run <slug> <value>`),
to fix a bug in an existing engine (edit it directly), or for anything that needs a
paid API key, a login, a CAPTCHA or paywalled data - propose a free/local substitute.

## Inputs to collect first

1. **What it does** in one sentence, and **when** someone would ask for it (3+ phrasings).
2. **Backend** - a free, keyless or local source (public API, local library, Ollama).
3. For engines: function name, typed arguments, and the network shape (`--network`,
   `--scrapes-web` -> robots-gated, `--needs-llm` -> degrades without Ollama).
4. For skills: the steps, the commands it runs, how its output is verified, and the
   tools it relies on.

## Step 1 - Generate

**An engine** (writes `openatlas/tools/<module>.py`, the import, the `methods.yaml`
block and `tests/test_<module>.py`):

```bash
python -m openatlas.utils.forge new-engine --engine DnsTxtEngine --common-name dns-txt \
  --abbrev dT --function lookup_txt --backend "dnspython (local)" --network
```

Then implement the body. Rules: return a `ToolResult`; use `openatlas.utils.http`
(`api_get_json` for APIs, `scrape_get` for pages - robots-gated); on an unreachable
backend return `ToolResult.unavailable(...)`; never send `Authorization`/`Cookie`.

**A skill** (writes a draft to `.claude/skill-drafts/<name>/SKILL.md` from the spec
template, lints it immediately, and promotes it to `.claude/skills/<name>/` only if it
passes - generation and verification are one command, and an unverified skill is never live):

```bash
python -m openatlas.utils.forge new-skill --name username-deep-dive \
  --description "What it does and when to use it (<=1024 chars)" \
  --trigger "Look up jdoe across the web" --trigger "Where else is jdoe?" \
  --trigger "Is this handle the same person?" \
  --step "Run the case" --command 'openatlas investigate "jdoe" --purpose "..."' \
  --verify "Every finding has a source URL and a verification status" \
  --tool "openatlas/investigate/verify.py - automatic re-checks"
```

`osint-investigate` and `kb-curate` in this repo were generated exactly this way. If the
lint fails, fix the draft and run `python -m openatlas.utils.forge verify-skill <name>`;
it is promoted as soon as it passes.

## Verification

Nothing is done until all of these pass:

```bash
python -m openatlas.utils.forge verify lookup_txt      # one engine function
python3 openatlas.py --verify                          # every function (44+)
python -m openatlas.utils.forge verify-skill --all     # every SKILL.md
python -m openatlas.utils.forge doctor                 # the verifying tools themselves
python -m pytest -q
```

1. **Engine function** (`openatlas/utils/smoke_run.py`): registered in `ToolRegistry`;
   has a `ToolSpec`; callable; documented in `methods.yaml` with a typed schema; if it
   calls `scrape_get` its spec says `scrapes_web=True`; no auth headers/cookies; no
   secrets; and a **mocked dry-run** (all HTTP -> 404, Ollama off) returns a valid
   `ToolResult`, which proves it degrades instead of crashing.
2. **Skill** (`openatlas/skills/linter.py`): frontmatter follows the agentskills.io
   rules (name 1-64 lowercase-hyphen chars matching the folder, description 1-1024);
   at least 3 trigger examples; a Verification section and a Tools section; **every
   `openatlas ...` command in a code block is executed with `--help` and must exit 0**;
   every referenced `openatlas/...` file and `openatlas.*` module exists; no secret or
   paid-key literal.
3. **Tool doctor** (`openatlas/skills/doctor.py`): each tool above is itself run against
   a known-good and a known-bad fixture - e.g. the secret lint must catch a planted
   fake key and then scan the installed package by absolute path (never your current
   folder, never a virtualenv) and report how many files it checked, the schema validator
   must reject a broken `methods.yaml`, the robots guard must block `/private`, the
   scaffolder does a full round-trip in a temp directory (never touching the repo), the
   evidence verifier must label confirmed / refuted / unverified correctly, and the brain
   check stores a fixture article in a throwaway brain and must find it (and nothing for a
   nonsense query) before sampling your real brain. `doctor --live` also probes each public source once from your
   network and reports which ones answer.

Report the JSON/summary back. If any check fails, fix and re-run - never report
success on a failing check.

## Tools this skill needs

| Tool | Module | Why it makes the output trustworthy |
|---|---|---|
| Scaffolder | `openatlas/utils/forge.py` | Writes engine / methods.yaml / pytest / SKILL.md consistently. |
| Smoke / dry-run runner | `openatlas/utils/smoke_run.py` | Runs every function with the network mocked; catches crashes and bad result shapes offline. |
| Schema + ToolResult validator | `openatlas/utils/schema_validate.py` | Docs and registry can't drift; every result has the same envelope. |
| Skill linter | `openatlas/skills/linter.py` | Spec-valid frontmatter, required sections, and commands that actually run. |
| robots.txt guard | `openatlas/utils/robots.py` | Scrapers stay robots-gated. |
| Network policy | `openatlas/net/client.py` | Strips credentials, caps bodies, never fetches data-broker sites. |
| Secret / paid-key lint | `openatlas/utils/secret_lint.py` | No hardcoded credential or paid-API-key literal gets in (intentional test fixtures carry `# secret-lint: ignore`). |
| Evidence verifier | `openatlas/investigate/verify.py` | Findings get independent re-checks, not echoed claims. |
| Local AI probe | `openatlas/llm/ollama_client.py` | Detects missing Ollama/GPU so LLM tools degrade instead of erroring. |
| Brain store + search | `openatlas/kb/store.py`, `openatlas/kb/retrieve.py` | Skills that answer from the brain get cited, retrievable passages. |
| Tool doctor | `openatlas/skills/doctor.py` | Verifies all of the above on fixtures - the verifiers are verified. |

## Definition of done

- `forge verify <function>` / `openatlas.py --verify` report `ok: true`.
- `forge verify-skill --all` reports OK for every skill; `forge doctor` has no FAIL.
- `pytest`, `ruff check openatlas` and `python -m openatlas.utils.secret_lint openatlas` are clean.
- No paid key; public, unauthenticated data only; scrapers robots-gated.
