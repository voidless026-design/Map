---
name: feature-planning
description: >-
  Plan a feature or bug fix test-first as an editable checklist: requirements, design, failing tests first, the smallest implementation, verification gates, a security/quality review, and risks with a rollback. Use when the user says 'plan a feature to...', 'how should I build...', 'plan this fix', or 'break this refactor down'. Verifies that tests always come before code and that the plan ends with verify and review. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): planner, architect and tdd-guide agents, tdd-workflow skill, /plan and /tdd commands.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# feature-planning

Make every build start from tests and end at verified, reviewed code. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- Plan a feature to add login to my app
- How should I build an export button?
- Plan this bug fix test-first
- Break this refactor down into steps

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Describe the feature or fix; E.V calls plan_feature and shows an editable checklist.
2. Work through it: requirements, design, failing tests, implementation.
3. Finish with verification-loop (every gate passes) and code-audit (no critical/high findings).

```bash
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill feature-planning
python -m openatlas.utils.forge doctor
```

1. pytest tests/test_ev_engineering.py::test_feature_plans_put_tests_before_code_and_end_with_verify_and_review passes.
2. The plan card saves every edit (interactive-planning).
3. The verify and review steps name the tools that check them.

## Tools this skill needs

- openatlas/ev/skills/engineering.py plan_feature - the test-first template
- openatlas/ev/skills/planning.py - the editable plan card

## Definition of done

- `python -m openatlas.utils.forge verify-skill feature-planning` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
