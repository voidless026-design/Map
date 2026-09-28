---
name: quality-assurance
description: >-
  Check every factual answer E.V gives, claim by claim, against the sources she used - supported, unsupported (e.g. a number that isn't in the source) or unverified - so the user no longer has to fact-check an AI by hand. Use when the user asks 'is that true?', 'fact-check this', 'double-check your answer', pastes AI output to verify, or after any research or document answer (it runs automatically). Verifies with the doctor's known-good/known-bad claims (a planted wrong number must be flagged), and adjusts E.V's per-source trust as claims are confirmed or refuted.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# quality-assurance

Check every factual answer E.V gives, claim by claim, against the sources she used - supported, unsupported (e.g. a number that isn't in the source) or unverified - so the user no longer has to fact-check an AI by hand. Use when the user asks 'is that true?', 'fact-check this', 'double-check your answer', pastes AI output to verify, or after any research or document answer (it runs automatically). Verifies with the doctor's known-good/known-bad claims (a planted wrong number must be flagged), and adjusts E.V's per-source trust as claims are confirmed or refuted.

## When to trigger

- Is that true? Double-check your last answer.
- Fact-check this paragraph I got from another AI.
- Which of those claims can you actually back up?
- Why is that sentence marked unsupported?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Nothing to do for normal answers: the Quality check card appears under every sourced reply.
2. For pasted text, ask E.V to fact-check it; she calls check_claims (against the brain if no sources are given).
3. Open the card to see each claim's verdict and the reason (e.g. 'the number isn't in the source').

```bash
openatlas doctor
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill quality-assurance
python -m openatlas.utils.forge doctor
```

1. The doctor's 'E.V quality check (claims)' check passes: supported, planted-wrong-number and unrelated claims are labelled correctly.
2. Any unsupported claim is shown in amber and E.V's source trust for that source drops.
3. pytest tests/test_ev.py::test_quality_assurance_labels_claims passes.

## Tools this skill needs

- openatlas/ev/skills/qa.py - claim splitter, lexical entailment, number and negation checks, optional local-model judge
- openatlas/ev/state.py - trust calibration per source
- openatlas doctor - known-good / known-bad claims

## Definition of done

- `python -m openatlas.utils.forge verify-skill quality-assurance` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
