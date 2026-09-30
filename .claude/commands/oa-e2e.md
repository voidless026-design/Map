---
description: Run (and extend) the headless-Chromium GUI end-to-end check against the offline mock server, then review the screenshots.
argument-hint: optional journey to add, e.g. "E.V reviews an uploaded file"
---
<!-- Adapted from everything-claude-code commands/e2e.md (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

E2E: $ARGUMENTS (empty means run the existing checks).

Use the **e2e-runner** agent:

1. If a journey is named, add `ok(...)` checks for it to `tests/e2e/gui_e2e.js` (wait on
   state, not time; use stable ids), and a mock for it in `tests/e2e/serve_mock.py` if needed.
2. Run it:
   ```bash
   python3 tests/e2e/serve_mock.py &
   node tests/e2e/gui_e2e.js /tmp/shots
   ```
   (first time: `pip install libzim` and `npm i playwright && npx playwright install chromium`).
3. Stop the mock server afterwards.
4. Open the screenshots and check layout, overlaps, cut-off text and both themes.
5. Report PASS/FAIL counts and every failure with its message.

A failing check is a bug to root-cause. Never skip or loosen a check to get green.
