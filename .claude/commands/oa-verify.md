---
description: Run the exact OpenAtlas CI gate (ruff, secret lint, pytest, self-verifier, doctor, skill lint) and report PASS/FAIL per gate. Not done until every gate passes.
argument-hint: quick | full (default) | pre-pr
---
<!-- Adapted from everything-claude-code commands/verify.md and skills/verification-loop (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Verify the working tree. Mode: $ARGUMENTS (empty means `full`).

Run the gates in this order and keep going after a failure so the report is complete:

```bash
ruff check openatlas tests
python -m openatlas.utils.secret_lint openatlas
python -m pytest -q
python openatlas.py --verify
python -m openatlas.utils.forge doctor
python -m openatlas.utils.forge verify-skill --all
```

- `quick`: only the first three.
- `full`: all six, plus the doctor from outside the repo (`cd .. && openatlas doctor`), because
  CI runs it that way.
- `pre-pr`: `full`, plus the suite without httpx2 (CI doesn't have it):
  `python -c "import sys; sys.modules['httpx2']=None; import pytest; sys.exit(pytest.main(['-q']))"`,
  a secret scan of the whole checkout (`python -m openatlas.utils.secret_lint .`), the
  **code-reviewer** agent on `git diff origin/main...HEAD`, and the e2e (`/oa-e2e`) if anything
  under `openatlas/web` or the visualizer changed.

Report:
```
VERIFY: PASS | FAIL
ruff        OK | N issues
secrets     OK | N findings
pytest      N passed | N failed
--verify    OK | FAIL
doctor      OK | N FAIL, N WARN
skills      OK | N failing
Ready for PR: YES | NO
```
For each failure show the last lines of its output and the likely fix. Use the
**build-error-resolver** agent to fix failures if asked.
