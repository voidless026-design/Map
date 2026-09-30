---
name: code-audit
description: >-
  Review a code file or folder for security and quality problems - hardcoded secrets, SQL built from strings, eval/exec, shell=True, unsafe deserialisation, TLS checks off, swallowed exceptions, long functions, missing tests - graded critical/high/medium/low with file, line and why. Use when the user says 'review this code', 'is this script safe', 'security check my repo', or 'audit this folder'. Verifies with the doctor's planted-bug fixture (every bug found, the clean file passes) and only reads folders the user allowed. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): code-reviewer and security-reviewer agents, security-review skill.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# code-audit

Replace reading code line by line for the usual security and quality traps. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- Review the code in ~/Documents/scraper.py
- Is this script safe to run?
- Security check my project folder
- Audit this repo before I publish it

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask E.V to review a file or folder in your allowed folders; she calls review_code.
2. Read the card: worst findings first, each with file:line and why it matters; the verdict says block / fix soon / ok.
3. Fix the critical and high findings first, then ask her to review again.

```bash
openatlas ev chat
openatlas doctor
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill code-audit
python -m openatlas.utils.forge doctor
```

1. The doctor's 'E.V engineering skills' check passes: a planted secret, SQL string, eval and shell=True are all found and a clean file passes.
2. pytest tests/test_ev_engineering.py passes (review, allowed folders).
3. Files outside the allowed folders are refused.

## Tools this skill needs

- openatlas/ev/skills/engineering.py review_code - the rules, graded findings and verdict
- openatlas/utils/secret_lint.py - the same secret scanner the project uses on itself

## Definition of done

- `python -m openatlas.utils.forge verify-skill code-audit` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
