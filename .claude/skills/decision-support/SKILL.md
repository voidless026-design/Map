---
name: decision-support
description: >-
  Help the user decide between options with a weighted matrix - criteria and weights, 0-10 scores, cost/risk/effort counted lower-is-better - plus a risk read-out and a sensitivity check that says whether a small change in priorities would flip the answer. Use when the user says 'should I… or…', 'which is better', 'help me decide', 'compare these options', or 'pros and cons'. Verifies that the maths is reproducible, that lower-is-better criteria are inverted, that a high-risk winner is flagged with the safer option, and that the recommendation states its confidence.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# decision-support

Help the user decide between options with a weighted matrix - criteria and weights, 0-10 scores, cost/risk/effort counted lower-is-better - plus a risk read-out and a sensitivity check that says whether a small change in priorities would flip the answer. Use when the user says 'should I… or…', 'which is better', 'help me decide', 'compare these options', or 'pros and cons'. Verifies that the maths is reproducible, that lower-is-better criteria are inverted, that a high-risk winner is flagged with the safer option, and that the recommendation states its confidence.

## When to trigger

- Should I buy a laptop or a desktop?
- Help me decide between three job offers.
- Compare Rust, Go and Python for my tool.
- Which car: the ute or the hatchback?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask the question; E.V calls decision_matrix with the options and criteria.
2. If she asks for scores, give 0-10 per option per criterion (or let her propose them).
3. Read the card: bars per option, confidence, sensitivity notes and any risk warning.

```bash
openatlas ev chat
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill decision-support
python -m openatlas.utils.forge doctor
```

1. Totals are the weighted average of scores, with cost/risk/effort inverted.
2. The sensitivity line lists any weight change of ±25% that flips the winner.
3. A winner with risk ≥7/10 gets a warning naming the safer option.
4. pytest tests/test_ev.py::test_decision_support_matrix_sensitivity_and_risk passes.

## Tools this skill needs

- openatlas/ev/skills/decisions.py - weighted matrix, sensitivity, risk note
- openatlas/ev/persona.py - the risk-assessment dial sets how cautious the warning is

## Definition of done

- `python -m openatlas.utils.forge verify-skill decision-support` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
