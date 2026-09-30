---
name: verification-loop
description: >-
  Run a project's own quality gates - tests, lint, secret scan and, for OpenAtlas, the doctor - and report pass/fail per gate with the failing lines, so work is only called done when every gate passes. Use when the user says 'run the tests', 'verify my project', 'does it pass', or 'is it ready for a PR'. Verifies that it only runs a fixed per-project-type command list after approval, never arbitrary shell. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): verification-loop skill and /verify command.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# verification-loop

Stop guessing whether a change is done: one approved run of every gate. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- Run the tests for ~/Documents/myproject
- Verify my project before I open a PR
- Does it build and pass?
- Is my change ready?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask E.V to verify a project folder; she queues verify_project for your approval (it runs commands).
2. Approve it: each gate (tests, lint, secrets, doctor) runs in turn.
3. Read the card: pass/fail per gate and the last lines of any failure; fix and verify again until all pass.

```bash
openatlas ev chat
openatlas doctor
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill verification-loop
python -m openatlas.utils.forge doctor
```

1. The doctor's 'E.V engineering skills' check passes: a passing and a failing fixture project are reported correctly.
2. pytest tests/test_ev_engineering.py::test_verify_needs_approval_then_reports_every_gate passes.
3. Nothing runs before approval, and only whitelisted commands run.

## Tools this skill needs

- openatlas/ev/skills/engineering.py verify_project - project detection, whitelisted gates, pass/fail table
- openatlas/ev/tools.py - the approval gate for command tools

## Definition of done

- `python -m openatlas.utils.forge verify-skill verification-loop` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
