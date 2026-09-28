---
name: workflow-automation
description: >-
  Turn routine OpenAtlas chores into named, scheduled routines that E.V runs for the user - growing the brain, resuming Kiwix downloads, checking search quality, running the doctor, writing research digests - each approved once, with a log of every run. Use when the user says 'every morning at 7…', 'automate…', 'set up a routine', 'run my routine now', or 'what routines do I have'. Verifies that only whitelisted steps are accepted, that creating or changing a routine needs approval, that schedules fire only after their slot, and that every run is logged.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# workflow-automation

Turn routine OpenAtlas chores into named, scheduled routines that E.V runs for the user - growing the brain, resuming Kiwix downloads, checking search quality, running the doctor, writing research digests - each approved once, with a log of every run. Use when the user says 'every morning at 7…', 'automate…', 'set up a routine', 'run my routine now', or 'what routines do I have'. Verifies that only whitelisted steps are accepted, that creating or changing a routine needs approval, that schedules fire only after their slot, and that every run is logged.

## When to trigger

- Every morning at 7, grow the brain and check search quality.
- Set up a weekly digest on quantum computing every Monday at 9.
- What routines do I have?
- Run my morning routine now.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Describe the routine; E.V proposes create_routine with allowed steps and a schedule.
2. Approve the card; the brain daemon runs it when due (or say 'run it now' and approve).
3. Check runs in Settings → Routines (last run + log) or ask 'what routines do I have'.

```bash
openatlas ev chat
openatlas ev approvals
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill workflow-automation
python -m openatlas.utils.forge doctor
```

1. Steps outside the whitelist (brain_ingest, library_resume, search_eval, doctor, research_digest) are rejected.
2. create_routine and run_routine always wait for approval.
3. A routine is due only after today's slot and not twice for the same slot (workflows.is_due).
4. Each run appends a log entry with per-step results.

## Tools this skill needs

- openatlas/ev/skills/workflows.py - whitelist, schedules, execute + log, run_due for the daemon
- openatlas/ev/tools.py - approval gate
- openatlas/kb/daemon.py - runs due routines in the background

## Definition of done

- `python -m openatlas.utils.forge verify-skill workflow-automation` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
