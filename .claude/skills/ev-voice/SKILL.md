---
name: ev-voice
description: >-
  Set up and check E.V's voice: hands-free conversation with low latency, all on this PC - faster-whisper hears you, the local model thinks, and MeloTTS speaks with an Australian (EN-AU) voice; talking over her stops her at once. Use when the user says 'talk to me', 'I want to speak to E.V', 'the mic doesn't work', 'set up her voice', or asks why she sounds robotic. Verifies end-of-speech detection, early first-sentence speech, the voice worker protocol and its latency, and reports what is still to install.
license: MIT
metadata:
  project: OpenAtlas
  generated_by: skill-forge
---

# ev-voice

Set up and check E.V's voice: hands-free conversation with low latency, all on this PC - faster-whisper hears you, the local model thinks, and MeloTTS speaks with an Australian (EN-AU) voice; talking over her stops her at once. Use when the user says 'talk to me', 'I want to speak to E.V', 'the mic doesn't work', 'set up her voice', or asks why she sounds robotic. Verifies end-of-speech detection, early first-sentence speech, the voice worker protocol and its latency, and reports what is still to install.

## When to trigger

- Set up E.V's voice so I can talk to her.
- The mic button says I need to install something.
- Why does she sound robotic?
- How fast does she answer when I speak?

Do **not** trigger it for anything that needs a paid API key, a login, or data that is not
publicly visible - OpenAtlas policy forbids those.

## Steps

1. Install hearing: pip install -e '.[voice]' (faster-whisper).
2. Install her Australian voice: sudo dnf install python3.11, then openatlas ev voice-setup (creates a voice venv and plays a test phrase).
3. In Atlas press the mic once and just talk; the System panel shows hear / think / speak times.

```bash
openatlas ev status
openatlas ev voice-setup
openatlas doctor
```

## Verification

This skill is only done when every check below passes:

```bash
python -m openatlas.utils.forge verify-skill ev-voice
python -m openatlas.utils.forge doctor
```

1. openatlas ev status shows hearing and voice as ready.
2. The doctor's 'E.V voice pipeline' check passes its fixtures and stops warning once both are installed.
3. Speaking over E.V stops her within one audio frame and she listens again.
4. pytest tests/test_ev_voice.py passes.

## Tools this skill needs

- openatlas/ev/voice.py - endpointing, sentence splitter, WebSocket session, barge-in
- openatlas/ev/tts_worker.py - MeloTTS EN-AU worker in its own venv
- faster-whisper (MIT) - local speech recognition

## Definition of done

- `python -m openatlas.utils.forge verify-skill ev-voice` reports ok.
- Every claim in the output carries a source link and a verification status.
- No paid key, no login, robots.txt respected.
