---
name: context-continuity
description: >-
  Give E.V a memory the user controls: conversations persist locally, a rolling summary keeps long chats coherent, and 'remember that…' facts carry across chats - always listable, editable and forgettable. Use when the user says 'remember that…', 'forget…', 'what do you know about me', 'continue where we left off', or refers to an earlier chat. Verifies that nothing is remembered without being told, that every fact is visible in Settings and via openatlas ev memory, and that forgetting removes it everywhere.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# context-continuity

Give E.V a memory the user controls: conversations persist locally, a rolling summary keeps long chats coherent, and 'remember that…' facts carry across chats - always listable, editable and forgettable. Use when the user says 'remember that…', 'forget…', 'what do you know about me', 'continue where we left off', or refers to an earlier chat. Verifies that nothing is remembered without being told, that every fact is visible in Settings and via openatlas ev memory, and that forgetting removes it everywhere.

## When to trigger

- Remember that I prefer metric units.
- What do you remember about me?
- Forget my home suburb.
- Pick up where we left off yesterday about the trip.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Say 'remember that …' (works even without the local model) or add it in Settings.
2. E.V uses remembered facts and a summary of older turns in every reply.
3. Review or delete facts in Settings → What E.V remembers, or openatlas ev memory.

```bash
openatlas ev memory
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill context-continuity
python -m openatlas.utils.forge doctor
```

1. A fact appears in openatlas ev memory right after 'remember that…'.
2. 'forget …' (or the Forget button) deletes it and E.V no longer uses it.
3. Conversations and facts live only in OPENATLAS_DATA_DIR/ev/ev.sqlite on this PC.
4. pytest tests/test_ev.py passes.

## Tools this skill needs

- openatlas/ev/memory.py - conversations, summaries, facts, search across chats
- openatlas/ev/skills/continuity.py - remember / recall / forget tools
- openatlas ev memory - list and forget from the terminal

## Definition of done

- `python -m openatlas.utils.forge verify-skill context-continuity` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
