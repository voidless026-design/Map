---
name: answer-evals
description: >-
  Measure how reliable E.V is on a question that matters: ask the local model k times and check each answer against the expected facts - every name and number must be there and nothing may contradict them - reporting pass@k (any run right) and pass^k (all runs right). Use when the user says 'how reliable is your answer to...', 'test yourself on...', 'eval this question', or 'can I trust you on...'. Verifies the pass@k maths on known inputs and that a wrong name or number fails the run. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code): eval-harness skill and /eval command.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# answer-evals

Replace hand-checking whether E.V answers something consistently right. Adapted from everything-claude-code (MIT, github.com/affaan-m/everything-claude-code).

## When to trigger

- How reliable is your answer to 'what is the capital of Australia'?
- Test yourself 5 times on the Kiwix resume command
- Eval this question against these facts
- Can I trust you on dates of World War II?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Give the question and the expected facts; E.V calls eval_answers (default 3 runs).
2. Read the card: each run's answer, whether it passed, and which names/numbers were missing.
3. pass@k says she can get it right; pass^k says she gets it right every time - trust the second.

```bash
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill answer-evals
python -m openatlas.utils.forge doctor
```

1. pytest tests/test_ev_engineering.py::test_pass_at_k_maths and ::test_eval_answers_with_the_local_model pass.
2. A wrong name or number in an answer fails that run.
3. With the local model off it says so instead of guessing.

## Tools this skill needs

- openatlas/ev/skills/engineering.py eval_answers / answer_ok / pass_at_k
- openatlas/ev/skills/qa.py - the claim checker, reused against each answer

## Definition of done

- `python -m openatlas.utils.forge verify-skill answer-evals` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
