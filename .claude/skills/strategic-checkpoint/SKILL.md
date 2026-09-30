---
name: strategic-checkpoint
description: >-
  Checkpoint a long conversation: fold everything so far into a short summary of goals, decisions and open items, so later replies stay fast and focused on a small local model - nothing is deleted. Use when the user says 'checkpoint this chat', 'summarise the chat so far', 'you're getting slow', or when E.V offers one after a long chat. Verifies that after a checkpoint only newer messages are sent verbatim and the summary carries the rest. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): strategic-compact skill and /checkpoint command.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# strategic-checkpoint

Keep long chats quick on local models by compacting at sensible points, not at random. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- Checkpoint this chat
- Summarise the chat so far and carry on
- You're getting slow - compact this conversation
- Carry forward that we chose the 2D brain

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Say 'checkpoint this chat' (optionally with what to carry forward); E.V calls checkpoint.
2. She shows the summary she'll carry forward; older messages stay in the history but aren't re-sent.
3. E.V offers a checkpoint by herself when a chat gets long - it's never automatic.

```bash
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill strategic-checkpoint
python -m openatlas.utils.forge doctor
```

1. pytest tests/test_ev_engineering.py::test_checkpoint_folds_the_chat_into_the_summary_and_shortens_the_context passes.
2. After a checkpoint, recent_for_model sends only messages newer than the checkpoint.
3. The offer appears after a long chat and not again right after a checkpoint.

## Tools this skill needs

- openatlas/ev/skills/engineering.py checkpoint / suggest_checkpoint
- openatlas/ev/memory.py recent_for_model - honours the checkpoint

## Definition of done

- `python -m openatlas.utils.forge verify-skill strategic-checkpoint` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
