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
  than asserting it. Runs automatically at the end of every `openatlas investigate` case;
  use it by hand for pasted outputs or older results.
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

## Automatic mode (default since v2)

You rarely need to run this by hand any more. Every `openatlas investigate` case (CLI or
GUI) ends with an automatic pass in `openatlas/investigate/verify.py`:

- **accounts** found by WhatsMyName -> the profile page is opened (robots-gated) and must
  load **and** show the username -> *confirmed*; a 404 -> *refuted*; anything else ->
  *unverified* with the HTTP status as the reason;
- **breaches** -> cross-checked against the second XposedOrNot endpoint;
- **first-party API** results (GitHub, Keybase, Reddit, HN...) are marked confirmed with
  the API named as the method;
- everything else (search snippets, Holehe, reverse-image links) is labelled
  *unverified* **with the reason**, never silently passed;
- `openatlas/investigate/correlate.py` then raises confidence only when independent
  domains agree.

The GUI shows the badge and the "why" on every evidence card; the Markdown report
shows the same. The manual commands below remain for pasted outputs and old results.

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

## Tools this skill needs

| Tool | Module | Why |
|---|---|---|
| Automatic re-checker | `openatlas/investigate/verify.py` | Runs on every case; labels confirmed / refuted / unverified with a reason. |
| Correlator | `openatlas/investigate/correlate.py` | Confidence rises only with independent sources. |
| Manual verifier | `openatlas/utils/verify_findings.py` | Re-checks pasted or older outputs by finding type. |
| Bounded HTTP client | `openatlas/net/client.py` | Robots-gated page fetches, capped bodies, no credentials, no data brokers. |
| Tool doctor | `openatlas/skills/doctor.py` | Its "Evidence verifier" check proves the three labels come out right on fixtures. |

```bash
openatlas doctor   # includes the evidence-verifier self-test
```

## Verification

The verifier is itself verified: `openatlas doctor` feeds it a profile page showing the
username, a 404, and a page without the username, through a mock transport, and
requires confirmed / refuted / unverified respectively. A report is acceptable only when every row has a `verified`
value (true / false / null), a named method or source, and - for null - a reason.

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
