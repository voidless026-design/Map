---
name: continuous-learning
description: >-
  Keep the lessons from a session: when something tricky gets solved, E.V drafts a reusable pattern (problem, what worked, when to use it) and saves it after approval, so it can be recalled and reused later - listable and forgettable. Use when the user says 'learn from this', 'save this fix', 'remember how we solved that', or 'what have we learned'. Verifies that nothing is saved without approval and that forgetting removes it everywhere. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): continuous-learning skill and /learn command.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# continuous-learning

Turn one-off fixes into reusable knowledge without cluttering memory. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- Learn from this - save how we fixed the Kiwix download
- Remember how we solved that pip error
- What have we learned so far?
- Forget the lesson about the old venv

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. After solving something, say 'learn from this'; E.V drafts a pattern and queues learn_pattern for approval.
2. Approve it: it's saved as a note in E.V's data folder and remembered.
3. Ask 'what have we learned' to list them, or 'forget the lesson about ...' to remove one.

```bash
openatlas ev chat
openatlas ev memory
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill continuous-learning
python -m openatlas.utils.forge doctor
```

1. The doctor's 'E.V engineering skills' check passes: learn_pattern waits for approval.
2. pytest tests/test_ev_engineering.py::test_learning_waits_for_approval_then_can_be_recalled_and_forgotten passes.
3. Every learned pattern shows in list_learned and in Settings > memory.

## Tools this skill needs

- openatlas/ev/skills/engineering.py learn_pattern / list_learned / forget_learned
- openatlas/ev/memory.py - so recall finds learned patterns

## Definition of done

- `python -m openatlas.utils.forge verify-skill continuous-learning` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
