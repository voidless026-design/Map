---
description: Save, compare or list named checkpoints of the working tree (git commit + test count), so you can see what changed since a known-good point.
argument-hint: create name | verify name | list
---
<!-- Adapted from everything-claude-code commands/checkpoint.md and skills/strategic-compact (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Checkpoint action: $ARGUMENTS

Checkpoints are lines in `.claude/checkpoints.log` (git-ignored):
`date | name | commit | dirty files | pytest passed/failed`.

- **create NAME:** run `python -m pytest -q` and `ruff check openatlas tests`; record
  `git rev-parse --short HEAD`, the count of changed files from `git status --short`, and the
  test counts. Don't commit or stash anything unless the user asks.
- **verify NAME:** read that line; show `git diff --stat` from its commit to the working tree,
  re-run the tests, and compare:
  ```
  CHECKPOINT NAME
  files changed since: N
  tests: +N passing / -N failing versus then
  ```
- **list:** show every checkpoint with its commit and whether HEAD is ahead of it.

For long sessions: after a checkpoint is a good moment to `/compact`, because the log (plus the
plan) carries what matters forward. E.V has the same idea for long chats (`checkpoint` tool,
the `strategic-checkpoint` skill).
