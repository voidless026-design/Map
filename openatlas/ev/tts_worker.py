"""E.V's voice worker: MeloTTS with the Australian English (EN-AU) speaker, in its own venv.

MeloTTS pins old libraries (transformers 4.27) that don't install on newer Pythons, so it
runs here - a tiny stdlib-only loop in a separate Python 3.11 virtualenv made by
``openatlas ev voice-setup`` - and OpenAtlas talks to it over stdin/stdout:

    request  (one JSON line):  {"id": 1, "text": "G'day!", "speed": 1.0}
    response (one JSON line):  {"id": 1, "rate": 44100, "bytes": 88200}  followed by that many
                               bytes of mono int16 PCM (or {"id": 1, "error": "..."})

The model loads once and stays warm, so each sentence costs only its synthesis time.
``OPENATLAS_EV_TTS_FAKE=1`` swaps in a tone generator (used by the tests, no model needed).
"""

import json
import math
import os
import struct
import sys


def _fake():
    rate = 24000

    def synth(text, speed=1.0):
        n = int(rate * min(2.0, 0.05 * len(text)) / max(speed, 0.5))
        return rate, b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 210 * i / rate))) for i in range(n))
    return synth


def _melo():
    import numpy as np
    import torch
    from melo.api import TTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TTS(language="EN", device=device)
    spk = model.hps.data.spk2id
    voice = os.getenv("OPENATLAS_EV_VOICE", "EN-AU")
    speaker = spk[voice] if voice in spk else spk.get("EN-AU", next(iter(spk.values())))
    rate = int(model.hps.data.sampling_rate)

    def synth(text, speed=1.0):
        audio = model.tts_to_file(text, speaker, None, speed=speed, quiet=True)
        return rate, (np.clip(np.asarray(audio, dtype=np.float32), -1, 1) * 32767).astype(np.int16).tobytes()
    synth(".", 1.0)  # warm up the graph so the first real sentence is fast
    return synth


def main():
    out = sys.stdout.buffer
    try:
        synth = _fake() if os.getenv("OPENATLAS_EV_TTS_FAKE") else _melo()
        out.write((json.dumps({"ready": True}) + "\n").encode())
    except Exception as exc:  # report and exit: the app falls back to the browser voice
        out.write((json.dumps({"ready": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n").encode())
        out.flush()
        return 1
    out.flush()
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        try:
            rate, pcm = synth(str(req.get("text", ""))[:1000], float(req.get("speed", 1.0)))
            out.write((json.dumps({"id": req.get("id"), "rate": rate, "bytes": len(pcm)}) + "\n").encode())
            out.write(pcm)
        except Exception as exc:
            out.write((json.dumps({"id": req.get("id"), "error": f"{type(exc).__name__}: {exc}"}) + "\n").encode())
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
