---
description: Find and safely remove dead code, unused imports and duplicates, with the full test suite green before and after every removal.
argument-hint: optional path
---
<!-- Adapted from everything-claude-code commands/refactor-clean.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Clean up: $ARGUMENTS (empty means the whole `openatlas` package).

Use the **refactor-cleaner** agent:

1. Confirm the suite is green first: `python -m pytest -q`.
2. Find candidates: `ruff check openatlas tests --select F401,F811,F841` (plus
   `vulture openatlas --min-confidence 80` if vulture is installed).
3. Check each candidate against OpenAtlas's dynamic references (registries, `@source`, `@tool`,
   routes, CLI, `methods.yaml`, skills, e2e hooks) and grep for its name as a string.
4. Sort into safe / careful / risky; propose only the safe ones and wait for a yes.
5. Remove one group at a time, running `python -m pytest -q` and `ruff check openatlas tests`
   after each; revert any group that breaks something.
6. Summarise what was removed, what was kept and why.
