---
name: project-setup
description: >-
  Have E.V draft and create a new project (Python package, web page, research notebook, OSINT case folder or notes) with a README, checklist and starter files, without ever overwriting anything. Use when the user says 'set up a new project for…', 'scaffold a Python package', 'start a research folder on…', or 'create a case folder'. Verifies that the layout is shown before anything is written, that creation waits for approval with a risk read-out, and that existing files are skipped, never overwritten.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# project-setup

Have E.V draft and create a new project (Python package, web page, research notebook, OSINT case folder or notes) with a README, checklist and starter files, without ever overwriting anything. Use when the user says 'set up a new project for…', 'scaffold a Python package', 'start a research folder on…', or 'create a case folder'. Verifies that the layout is shown before anything is written, that creation waits for approval with a risk read-out, and that existing files are skipped, never overwritten.

## When to trigger

- Set up a Python project called Birdwatch.
- Start a research folder on coastal erosion.
- Create an OSINT case folder for my self-audit.
- Scaffold a small web page project.

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Ask E.V; she drafts the layout with plan_project (shows the files, writes nothing).
2. Press 'Create it…' on the card; an approval card appears with the risk appraisal.
3. Approve; she creates the folder under ~/Projects and reports what was written or skipped.

```bash
openatlas ev chat
openatlas ev approvals
openatlas ev approve 1
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill project-setup
python -m openatlas.utils.forge doctor
```

1. plan_project writes nothing to disk.
2. create_project only runs after the approval card is approved (openatlas ev approvals lists it).
3. Re-running create_project on an existing folder reports every file as skipped_existing and changes nothing.
4. The doctor's 'E.V approval gate' check passes.

## Tools this skill needs

- openatlas/ev/skills/project.py - templates per project kind, never-overwrite writer
- openatlas/ev/tools.py - approval gate + risk simulation
- openatlas ev approvals / openatlas ev approve - approve from the terminal

## Definition of done

- `python -m openatlas.utils.forge verify-skill project-setup` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
