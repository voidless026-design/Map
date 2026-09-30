---
description: Measure pytest coverage for the modules you changed and write the missing offline tests (error paths, edges, safety rules) until they reach about 80%.
argument-hint: optional module, e.g. openatlas/ev/skills
---
<!-- Adapted from everything-claude-code commands/test-coverage.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Coverage for: $ARGUMENTS (empty means the files changed on this branch).

1. `pytest-cov` is free; install it once if missing: `pip install pytest-cov`.
2. Measure:
   ```bash
   python -m pytest -q --cov=openatlas --cov-report=term-missing
   ```
3. For each changed module under ~80%, read the missed lines and use the **tdd-guide** agent to
   add offline tests for them: error paths (`ok=False`, `unavailable`), empty inputs, caps and
   timeouts, and the safety rules (approval gate, robots, allowed folders).
4. Re-run and show before/after percentages per module.

Don't write tests that only execute lines without asserting behaviour, and never mark tests skip.
