---
description: Build a feature or fix a bug test-first - failing pytest (offline), minimal code, refactor, suite green.
argument-hint: the behaviour to add or the bug to fix
---
<!-- Adapted from everything-claude-code commands/tdd.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Use the **tdd-guide** agent for: $ARGUMENTS

1. **RED:** write the test(s) in the matching `tests/test_*.py` using the offline fixtures
   (`mock_http`, `httpx.MockTransport`, `fake_ollama`, `tmp_path`). For a bug, reproduce it.
   Run it and show that it fails for the right reason:
   ```bash
   python -m pytest -q -x tests/test_ev_engineering.py
   ```
2. **GREEN:** write the minimal code; re-run the same test until it passes.
3. **REFACTOR:** tidy with the test green, then run:
   ```bash
   python -m pytest -q
   ruff check openatlas tests
   ```
4. If the change adds a verifier or an E.V tool, add or extend its doctor check
   (known-good and known-bad fixture).

Report the tests added, the RED output, and the final GREEN run. Never skip or weaken a test.
