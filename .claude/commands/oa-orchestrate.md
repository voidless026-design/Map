---
description: Run a chain of OpenAtlas agents for a task (feature, bugfix, refactor or security), passing a short handoff between them, and finish with the verify gate.
argument-hint: feature|bugfix|refactor|security and the task
---
<!-- Adapted from everything-claude-code commands/orchestrate.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Orchestrate: $ARGUMENTS

Workflows:
- **feature:** planner → (user approves the plan) → tdd-guide → code-reviewer → security-reviewer → e2e-runner if the GUI changed → doc-updater
- **bugfix:** tdd-guide (reproduce with a failing test first) → build-error-resolver if the build is red → code-reviewer
- **refactor:** architect → refactor-cleaner → code-reviewer
- **security:** security-reviewer → code-reviewer → architect

Between agents, pass a handoff:
```markdown
## HANDOFF: agent -> next agent
Context: what was done
Findings: decisions and discoveries
Files: touched files
Open: unresolved questions
Next: suggested steps
```

Run agents one after another when each needs the previous output; run independent reviews
(code-reviewer and security-reviewer on the same diff) in parallel. Stop at any agent that
reports a blocker and bring it to the user. Finish with `/oa-verify full` and a short report:
what changed, review verdicts, gate results, anything left open.
