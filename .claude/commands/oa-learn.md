---
description: Pull a reusable lesson out of this session (a root cause and its fix, a project quirk) and, after you confirm, save it where the next session will actually read it.
argument-hint: optional topic
---
<!-- Adapted from everything-claude-code commands/learn.md and skills/continuous-learning (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Extract a lesson from this session. Focus: $ARGUMENTS

Look for things that will save time next time:
- an error, its real root cause, and the fix (not the symptoms);
- a non-obvious debugging step or tool combination;
- a library or platform quirk (Python version, Fedora, nouveau, Firefox, Ollama);
- a project convention that wasn't written down.

Skip typos, one-off outages and anything already in CLAUDE.md.

Draft it as:
```markdown
**Problem:** ...
**Root cause:** ...
**What worked:** ...
**Use it when:** ...
```

Show the draft and ask where it goes. Save nothing without a yes:
- a rule for anyone editing a module: one line in `CLAUDE.md` under that module's layout note;
- a repeatable workflow: a skill, generated and linted with
  `python -m openatlas.utils.forge new-skill --name ... --description ... --trigger ... --trigger ... --trigger ...`
  and checked with `python -m openatlas.utils.forge verify-skill --all`;
- a user-facing fix: the README troubleshooting list.

E.V does the same for you in chat ("learn from this" → `learn_pattern`, saved only after you approve).
