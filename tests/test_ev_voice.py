"""E.V's voice pipeline with fake speech engines: endpointing, streaming sentences, barge-in."""

from __future__ import annotations

import json
import math
import struct

import pytest

from openatlas.ev import db, voice


def tone(ms: int, amp: int = 9000) -> bytes:
    n = voice.IN_RATE * ms // 1000
    return b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / voice.IN_RATE))) for i in range(n))


def silence(ms: int) -> bytes:
    return b"\x00\x00" * (voice.IN_RATE * ms // 1000)


class FakeSTT:
    def __init__(self, text="what's the capital of australia?"):
        self.text, self.calls = text, 0

    def transcribe(self, pcm):
        self.calls += 1
        return self.text


class FakeTTS:
    rate = 24000

    def __init__(self):
        self.said = []

    def synth(self, text, speed=1.0):
        self.said.append(text)
        return b"\x01\x00" * 2400  # 100 ms of audio


@pytest.fixture
def engines(monkeypatch, tmp_path):
    stt, tts = FakeSTT(), FakeTTS()
    monkeypatch.setattr(voice, "STT_FACTORY", lambda: stt)
    monkeypatch.setattr(voice, "TTS_FACTORY", lambda: tts)
    monkeypatch.setattr(voice, "_has", lambda mod: False)  # no webrtcvad: exercise the energy gate
    db.reset_init_cache()
    return stt, tts


def test_endpointer_finds_the_end_of_speech():
    ep = voice.Endpointer()
    ep.vad = None
    step = voice.IN_RATE * voice.FRAME_MS // 1000 * 2
    audio = silence(300) + tone(600) + silence(voice.END_SILENCE_MS + 60)
    got = [ep.feed(audio[i:i + step]) for i in range(0, len(audio), step)]
    assert any(g["started"] for g in got)
    utt = [g["utterance"] for g in got if g["utterance"]]
    assert len(utt) == 1 and len(utt[0]) >= voice.IN_RATE * 2 * 0.6
    ep2 = voice.Endpointer()
    ep2.vad = None
    clicks = tone(60) + silence(600)  # too short to be speech
    assert not any(ep2.feed(clicks[i:i + step])["utterance"] for i in range(0, len(clicks), step))


def test_sentence_splitter_speaks_early_and_cleanly():
    sp = voice.SentenceSplitter()
    out = []
    for tok in "Canberra is the capital [1]. It was **purpose-built** as a compromise. See https://x.y ok".split(" "):
        out += sp.push(tok + " ")
    out += sp.flush()
    assert out[0].startswith("Canberra is the capital") and len(out) >= 2
    assert "[1]" not in " ".join(out) and "**" not in " ".join(out) and "a link" in " ".join(out)
    assert voice.speakable("E.V here") == "Eevee here"


def _drain(ws, until, limit=400):
    got = []
    for _ in range(limit):
        m = ws.receive()
        if m.get("text") is not None:
            ev = json.loads(m["text"])
            got.append(ev)
            if until(ev):
                return got
        elif m.get("bytes") is not None:
            got.append({"type": "_audio", "n": len(m["bytes"])})
    raise AssertionError(f"never saw the end: {[g.get('type') for g in got][-20:]}")


def test_voice_turn_end_to_end(engines):
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    stt, tts = engines
    with TestClient(create_app()) as c, c.websocket_connect("/ws/ev/voice") as ws:
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready" and ready["stt"] and ready["tts"] == "server"
        ws.send_bytes(silence(200) + tone(700) + silence(voice.END_SILENCE_MS + 100))
        got = _drain(ws, lambda e: e["type"] == "timings" and "total_ms" in e)
    types = [g["type"] for g in got]
    assert types.index("transcript") < types.index("token") < types.index("audio_start")
    assert "_audio" in types and stt.calls == 1 and tts.said
    t = [g for g in got if g["type"] == "timings"][-1]
    assert t["stt_ms"] >= 0 and t["first_audio_ms"] >= t["first_token_ms"]


def test_typed_text_and_barge_in(engines):
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    with TestClient(create_app()) as c, c.websocket_connect("/ws/ev/voice") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"type": "text", "text": "hello E.V"}))
        _drain(ws, lambda e: e["type"] == "token")
        ws.send_text(json.dumps({"type": "interrupt"}))
        got = _drain(ws, lambda e: e["type"] == "audio_stop")
    assert got[-1]["type"] == "audio_stop"


def test_browser_voice_fallback(monkeypatch, engines):
    from fastapi.testclient import TestClient

    from openatlas.web.server import create_app

    monkeypatch.setattr(voice, "TTS_FACTORY", voice._default_tts)
    with TestClient(create_app()) as c, c.websocket_connect("/ws/ev/voice") as ws:
        assert json.loads(ws.receive_text())["tts"] == "browser"
        ws.send_text(json.dumps({"type": "text", "text": "hello there"}))
        got = _drain(ws, lambda e: e["type"] == "say")
    assert got[-1]["text"]


def test_status_explains_missing_engines(monkeypatch):
    monkeypatch.setattr(voice, "_has", lambda mod: False)
    s = voice.status()
    assert not s["stt"]["available"] and "pip install" in s["stt"]["hint"] and s["tts"]["voice"] == "EN-AU"


def test_sidecar_voice_worker_protocol(monkeypatch):
    """The real worker process + protocol, with the tone generator standing in for MeloTTS."""
    import sys

    monkeypatch.setenv("OPENATLAS_EV_TTS_PYTHON", sys.executable)
    monkeypatch.setenv("OPENATLAS_EV_TTS_FAKE", "1")
    assert voice.status()["tts"]["available"]
    tts = voice.SidecarTTS()
    try:
        a = tts.synth("G'day mate, how's it going?")
        b = tts.synth("Short.", speed=1.2)
        assert len(a) > len(b) > 0 and len(a) % 2 == 0 and tts.rate == 24000
    finally:
        tts.close()


def test_sidecar_missing_says_how_to_set_up(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENATLAS_EV_TTS_PYTHON", str(tmp_path / "nope" / "python"))
    assert voice.sidecar_python() is None
    with pytest.raises(RuntimeError, match="openatlas ev voice-setup"):
        voice.SidecarTTS()
    assert "voice-setup" in voice.status()["tts"]["hint"]
