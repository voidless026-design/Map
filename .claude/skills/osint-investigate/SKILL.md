---
name: osint-investigate
description: >-
  Run an evidence-based OpenAtlas investigation on a person, username, email, phone, domain, IP or image, and hand back only findings that carry a source link and an automatic verification status. Use when the user says 'look up this username', 'what is public about jdoe@example.com', 'investigate example.com', 'who owns 8.8.8.8', or pastes a target and asks what can be found. Every case needs a stated purpose (stored for the audit trail). Replaces the manual step of opening a browser to check each AI answer: osint-verify runs automatically on every finding and labels it confirmed, refuted or unverified.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# osint-investigate

OpenAtlas used to answer 'found: True' and the investigator then opened a browser to check it. This skill runs a full case instead: detect the target type, query every relevant free public source in parallel (bounded, with a deadline), read the top result pages (robots.txt respected), extract and correlate entities across independent sources, and automatically re-check each finding. The output is evidence, not booleans.

## When to trigger

- "Look up the username jdoe_42 across the web."
- "What is publicly known about jane@example.com?" (with a purpose such as 'verifying a job applicant with consent')
- "Investigate example.com - who runs it and what does it expose?"
- "Who owns 8.8.8.8?"
- A pasted target plus 'what can you find?'

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask for (or confirm) a one-line purpose; refuse targets that are private individuals without a legitimate purpose (see ETHICS.md).
2. Preview which sources will run: `openatlas catalog --filter <filter>`.
3. Run the case with `openatlas investigate` (add `--filter` or `--sources` to narrow it).
4. Read the Markdown report; present confirmed findings first, then unverified, and list refuted ones as ruled out.
5. Show the 'What was searched' section so failed or blocked sources are visible, never hidden.

```bash
openatlas catalog --filter username
openatlas investigate "jdoe_42" --purpose "authorised background check" --filter username
openatlas cases
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill osint-investigate
python -m openatlas.utils.forge doctor
```

1. Every finding in the report has a source URL (`Evidence.url`) - findings without one are dropped, not shown.
2. Every finding carries a status from the automatic osint-verify pass (`openatlas.investigate.verify`): confirmed / refuted / unverified, with the method and reason.
3. Confidence rises only with independent domains (`openatlas.investigate.correlate`); a single source never reaches 'confirmed' on its own unless it is the first-party API for that account.
4. Sources that failed or were blocked are listed with the reason; 'nothing found' is reported as a valid result.

## Tools this skill needs

- `openatlas/investigate/pipeline.py` - bounded async case runner (deadline, per-source timeouts)
- `openatlas/investigate/verify.py` - automatic osint-verify re-checks
- `openatlas/investigate/correlate.py` - cross-source corroboration
- `openatlas/net/client.py` - robots-gated, capped HTTP; skips data-broker sites
- `openatlas doctor` - verifies the verifier, network policy and robots guard before you trust a run

## Definition of done

- `python -m openatlas.utils.forge verify-skill osint-investigate` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
