---
description: Review uncommitted changes (or the branch against main) for security, the OpenAtlas non-negotiables, tests and quality; blocks on critical or high findings.
argument-hint: optional path or "branch"
---
<!-- Adapted from everything-claude-code commands/code-review.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Review: $ARGUMENTS (empty means uncommitted changes; `branch` means `git diff origin/main...HEAD`).

1. List the changed files: `git diff --name-only HEAD` (or against `origin/main` for `branch`).
2. Run the **code-reviewer** agent on them. If any file handles input, paths, the network,
   subprocesses, the web API or an E.V tool, also run the **security-reviewer** agent.
3. Run the automated checks:
   ```bash
   python -m openatlas.utils.secret_lint openatlas
   ruff check openatlas tests
   ```
4. Report findings worst first as `[SEVERITY] file:line - issue - fix`, then the verdict:
   **block** (critical/high), **fix soon** (medium only) or **ok**.

Never approve a change that breaks a CLAUDE.md non-negotiable. E.V's `review_code` tool uses
the same rules for code in your own folders (the `code-audit` skill).
