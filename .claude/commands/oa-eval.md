---
description: Eval-driven development - define capability and regression evals for a feature, check them (pass@k / pass^k), and report readiness. Covers code behaviour, search relevance and E.V's answers.
argument-hint: define name | check name | report name | list
---
<!-- Adapted from everything-claude-code commands/eval.md and skills/eval-harness (MIT, (c) 2026 Affaan Mustafa) at 432485b - see .claude/ECC-NOTICE.md -->

Eval action: $ARGUMENTS

Eval definitions live in `.claude/evals/NAME.md`:
```markdown
## EVAL: NAME
### Capability (new behaviour) - target pass@3 >= 90%
- [ ] ... (a pytest node id, a command, or a question + expected facts)
### Regression (must not break) - target pass^3 = 100%
- [ ] tests/test_x.py::test_y
### Success criteria
```

- **define NAME:** create the file from the template and ask the user for the criteria.
- **check NAME:** run each item k=3 times where it can vary, and once where it's deterministic:
  - code: `python -m pytest -q` on the listed node ids;
  - search relevance: `openatlas kb eval --fixture` (must stay passing after ranking changes);
  - E.V's answers: her `eval_answers` tool (asks the local model k times and checks each answer
    against the expected facts with the claim checker; the `answer-evals` skill).
  Append results to `.claude/evals/NAME.log`.
- **report NAME:** capability X/Y at pass@k, regression X/Y at pass^k, and READY or NOT READY.
- **list:** every eval with its last status.

pass@k = at least one of k runs passed; pass^k = all k runs passed.
