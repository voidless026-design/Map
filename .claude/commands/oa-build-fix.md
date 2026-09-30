---
description: Fix a red OpenAtlas build one root cause at a time (pytest, ruff, imports, --verify, doctor, skill lint), re-running after each fix, with minimal diffs.
argument-hint: optional failing check
---
<!-- Adapted from everything-claude-code commands/build-fix.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Fix the build. Focus: $ARGUMENTS

Use the **build-error-resolver** agent:

1. Collect every error:
   ```bash
   ruff check openatlas tests
   python -m pytest -q
   python openatlas.py --verify
   python -m openatlas.utils.forge doctor
   python -m openatlas.utils.forge verify-skill --all
   ```
2. Group by root cause, most upstream first.
3. For each cause: show the context, explain it, apply the smallest fix, re-run that check,
   and confirm nothing new broke.
4. Stop and ask if a fix needs a design change, the same error survives 3 attempts, or the
   failure is outside this change.
5. Summarise errors fixed, remaining and introduced.

Never skip, xfail or delete a test, and never disable a safety check to get green.
