---
description: Bring README.md, CLAUDE.md (the codemap), SKILL.md files and NOTICE in line with the code, with commands people can paste as-is.
argument-hint: optional area, e.g. kb library
---
<!-- Adapted from everything-claude-code commands/update-docs.md and commands/update-codemaps.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Update the docs for: $ARGUMENTS (empty means everything changed on this branch).

Use the **doc-updater** agent:

1. Read the truth from the code: `openatlas --help` and its subcommands, `pyproject.toml`,
   the `Makefile`, the `OPENATLAS_*` environment variables, and the doctor's `CHECKS`.
2. Update `README.md` (user steps, Fedora first), the `CLAUDE.md` layout notes (one or two lines
   per module), any SKILL.md the change affects, and `NOTICE` for adapted third-party work.
3. No `<placeholders>` in commands; use real examples.
4. Check:
   ```bash
   python -m openatlas.utils.forge verify-skill --all
   python -m openatlas.utils.forge doctor
   ```
5. List each file changed and each fact corrected.
