---
name: interactive-planning
description: >-
  Plan with E.V: she drafts a step-by-step checklist card in the chat that the user ticks, edits, reorders and extends, and she keeps open plans in view. Use when the user says 'help me plan…', 'break this down', 'what are the steps to…', or 'make a checklist'. Verifies that the plan card saves every edit, that investigations get the evidence-first steps (purpose, auto-plan, osint-verify), and that open plans show in the System panel until done.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# interactive-planning

Plan with E.V: she drafts a step-by-step checklist card in the chat that the user ticks, edits, reorders and extends, and she keeps open plans in view. Use when the user says 'help me plan…', 'break this down', 'what are the steps to…', or 'make a checklist'. Verifies that the plan card saves every edit, that investigations get the evidence-first steps (purpose, auto-plan, osint-verify), and that open plans show in the System panel until done.

## When to trigger

- Help me plan a weekend trip to the Blue Mountains.
- Break down moving house into steps.
- Make a checklist for investigating my own username.
- What's left on my plan?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask for a plan; E.V calls make_plan (with her own steps when the model is up).
2. Tick, edit (click the text), reorder (↑) or add steps right in the card.
3. Watch 'Open plans' in the System panel; ask E.V what's left.

```bash
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill interactive-planning
python -m openatlas.utils.forge doctor
```

1. Each tick/edit/add/move is saved (reload the chat and it's still there).
2. Plans for investigations include purpose, Auto-plan and osint-verify steps.
3. A finished plan leaves the open-plans count.
4. pytest tests/test_ev.py::test_planning_card_edit_cycle passes.

## Tools this skill needs

- openatlas/ev/skills/planning.py - make_plan, edit, open_plans
- openatlas/reasoning/loop.py - Auto-plan for investigations
- PATCH /api/ev/plans/{id} - card edits

## Definition of done

- `python -m openatlas.utils.forge verify-skill interactive-planning` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
