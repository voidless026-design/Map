# everything-claude-code in OpenAtlas

OpenAtlas adapts parts of **everything-claude-code**:
- upstream: https://github.com/affaan-m/everything-claude-code
- the fork we were pointed to: https://github.com/WorldFlowAI/everything-claude-code
- adapted at commit `432485b` (2026-01-23)

It's MIT-licensed; the notice is copied in full below. Every adapted file starts with a one-line
comment naming the file it came from.

## What was adapted

| everything-claude-code | OpenAtlas | How it changed |
|---|---|---|
| `agents/` (all 9) | `.claude/agents/` (same names) | Rewritten for Python, pytest, ruff and the OpenAtlas gate. The reviewers check the CLAUDE.md non-negotiables (no paid keys, public data only, robots gate, no auth headers, approval gate). |
| `commands/` plan, tdd, verify, code-review, checkpoint, learn, refactor-clean, test-coverage, update-docs (+ update-codemaps), eval, orchestrate, build-fix, e2e | `.claude/commands/oa-*.md` | Prefixed `oa-` so none of them shadow Claude Code's built-in `/code-review`, `/security-review` or `/plan`. `/oa-verify` runs the exact CI gate. |
| `skills/` security-review + code-reviewer | `.claude/skills/code-audit/` + E.V's `review_code` tool | Local static checks, reusing `openatlas.utils.secret_lint`. |
| `skills/verification-loop` | `.claude/skills/verification-loop/` + E.V's `verify_project` | A whitelist of checks per project type; runs only after your approval. |
| `skills/continuous-learning`, `commands/learn` | `.claude/skills/continuous-learning/` + E.V's `learn_pattern` | Lessons are saved only after you approve them, and are listed, recalled and forgotten on request. |
| `skills/strategic-compact`, `commands/checkpoint` | `.claude/skills/strategic-checkpoint/` + E.V's `checkpoint` | Folds a long chat into its summary so small local models stay fast. |
| `agents/planner`, `agents/tdd-guide`, `skills/tdd-workflow` | `.claude/skills/feature-planning/` + E.V's `plan_feature` | Seven steps, tests before code. |
| `skills/eval-harness`, `commands/eval` | `.claude/skills/answer-evals/` + E.V's `eval_answers` | pass@k / pass^k on the local model, graded by the claim checker. |
| `rules/` (agents, testing, security, git-workflow) | The "Working on OpenAtlas with Claude Code" section of `CLAUDE.md` | Folded in, because Claude Code doesn't load a separate rules folder. |

E.V's tools live in `openatlas/ev/skills/engineering.py`. They are written from scratch, with
no upstream code, and verified by the doctor check "E.V engineering skills".

## What was left out, and why
- **Web-stack-only material:** `skills/backend-patterns` (Express/Next), `frontend-patterns`
  (React), `clickhouse-io`, `coding-standards` (TypeScript/React) and
  `project-guidelines-example`. It doesn't apply to a Python/FastAPI/no-build project.
- **`commands/setup-pm`:** it chooses an npm/pnpm/yarn/bun package manager.
- **`hooks/`:** Node scripts that block tmux, block new `.md` files and enforce a package
  manager. They conflict with this repo's workflow (it keeps docs in Markdown) and need Node on
  every edit.
- **`mcp-configs/`:** they point at hosted services, some needing API keys or paid tiers.
  That breaks the "never introduce a paid API key or backend" rule.
- **`rules/coding-style` immutability and "many small files" rules:** they are
  JavaScript-specific. The Python equivalents (short functions, no swallowed exceptions) are in
  the code-reviewer agent.
- **`contexts/`, `examples/`, `plugins/`:** these are examples for other projects.

## Licence (MIT)

```
MIT License

Copyright (c) 2026 Affaan Mustafa

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
