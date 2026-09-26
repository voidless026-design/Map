---
name: osint-verify
description: >-
  Verify OSINT findings that an AI/LLM function produced, so the investigator doesn't
  have to re-check them by hand. Use whenever the user says "verify this geolocation",
  "confirm these username hits", "double-check this breach result", "is this email
  real?", or pastes an OpenAtlas/LLM output and asks whether to trust it. For each
  finding type it re-checks the claim against an INDEPENDENT free source (resolve the
  profile URL, cross-check coordinates against EXIF + OSM, confirm MX + Holehe, second
  breach source, agree/disagree across image detectors), then emits a corroboration
  table with a confidence per claim and explicitly flags anything unverifiable rather
  than asserting it.
license: MIT
metadata:
  project: OpenAtlas
  produces: [corroboration-table, confidence-scores]
---

# osint-verify — automate the "re-check the AI's answer" step

LLM-powered OSINT functions (image geolocation, username enumeration, email discovery,
breach lookups, AI-image detection) produce *claims*, not facts. Today the investigator
re-checks each claim by hand: does that profile URL actually resolve? are those
coordinates consistent with the photo's EXIF? is that email deliverable? is the breach
corroborated elsewhere? This skill does that re-checking automatically, against a
**different, free source** than the one that produced the claim, so a single tool's
mistake or hallucination doesn't slip through.

## When to trigger

- "Verify this geolocation guess." (an `geolocate_using_LLMs` output)
- "Confirm these username hits are real." (a `check_usernames` result)
- "Double-check whether this email is in a breach." (a breach result)
- "Is `jane.doe@acme.com` a real, deliverable address?"
- "This image was flagged AI-generated — is that reliable?"
- Any pasted OpenAtlas `ToolResult` where the user asks "can I trust this?".

Do **not** trigger it to *produce* findings (that's the engines/`skill-forge`); this
skill only *checks* findings that already exist.

## Verification method per finding type

Run the corresponding independent check and record source + outcome:

| Finding | Original source | Independent verification |
|---|---|---|
| **Username hit** (site → profile URL) | WhatsMyName existence rule | HTTP-GET the profile URL (robots-gated) and confirm a 200 **and** a presence marker (the username appearing in the page/title). A rule match without a resolving page → downgrade to "unconfirmed". |
| **Image geolocation** (lat/lon or place) | LLM vision inference | Read the image's EXIF GPS (`extract_metadata`); reverse-geocode the LLM's coordinates via OSM Nominatim and check the returned region matches the LLM's claimed region. Divergence between EXIF and LLM → flag conflict. |
| **Email deliverability** | permutation heuristic | `verify_email_address` (MX/A) + optional Holehe account-existence corroboration. No MX → "not deliverable". |
| **Breach hit** | XposedOrNot | Cross-check with a second keyless source (HIBP Pwned Passwords for password exposure; XposedOrNot analytics endpoint) and require agreement before "confirmed". |
| **AI-generated image** | one detector | Require agreement between metadata/C2PA signals and the local classifier; disagreement → "inconclusive", never a hard verdict. |
| **IP geolocation** | ip-api | Cross-check ipapi.co; mismatch on country → flag. |

## How to run it

Use the bundled verifier, which implements the table above:

```bash
# Verify a saved OpenAtlas ToolResult (JSON) or an ad-hoc claim:
python -m openatlas.utils.verify_findings --type username  --input result.json
python -m openatlas.utils.verify_findings --type geolocation --image photo.jpg --claim '{"latitude":48.85,"longitude":2.29,"region":"Paris"}'
python -m openatlas.utils.verify_findings --type email --claim jane.doe@acme.com
python -m openatlas.utils.verify_findings --type breach --claim jane.doe@acme.com
```

It returns a JSON **corroboration report**: for each claim a `verified` boolean (or
`null` when it can't be checked), the independent `source` used, the `evidence`, and a
`confidence` in `[0,1]`. Present it as a table and **call out every `verified: null`
row explicitly** — "could not confirm" is a first-class result, not a silent pass.

## Guardrails

- Public data only; every page fetch is robots-gated (`openatlas/utils/robots.py`).
- Never log in, solve CAPTCHAs, or bypass paywalls to "confirm" something.
- If the only available corroboration source is the same one that produced the claim,
  report the finding as **uncorroborated** rather than echoing it back as verified.

## Definition of done

- Every claim has an independent check result (`verified` true/false/null) with a named
  source and evidence.
- Unverifiable claims are flagged, not asserted.
- The output is a compact corroboration table plus the raw JSON for the record.
