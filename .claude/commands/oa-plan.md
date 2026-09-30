---
description: Restate the request, list risks, and write a step-by-step OpenAtlas plan with tests first. Waits for your go-ahead before any code is written.
argument-hint: what to build or change
---
<!-- Adapted from everything-claude-code commands/plan.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Plan this change to OpenAtlas: $ARGUMENTS

Use the **planner** agent (and the **architect** agent if it adds a subsystem, a schema change
or a dependency). The plan must:

1. Restate the request in plain words and list any question whose answer changes the plan.
2. Name the exact files, functions and tests, following the nearest existing example.
3. Put the failing tests first, then the smallest implementation, then the verification.
4. List the CLAUDE.md rules the change touches and how each stays enforced.
5. List risks, how it degrades without Ollama or the network, and how to roll it back.

Then STOP and wait for an explicit "go ahead". Do not edit code until then.
