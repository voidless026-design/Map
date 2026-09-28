"""E.V's voice: low-latency, fully local speech in and out over one WebSocket.

    mic (browser AudioWorklet, 16 kHz int16, 20 ms frames)
      -> endpointing (WebRTC VAD if installed, else an adaptive energy gate; ~450 ms of silence)
      -> faster-whisper (small.en on GPU / base.en on CPU, loaded once)
      -> E.V's agent (streaming tokens)
      -> sentence splitter -> MeloTTS EN-AU (the Australian English voice) per sentence
      -> PCM chunks back to the browser, played gaplessly.

Barge-in: when you start talking while she speaks, the browser stops playback at once and sends
``interrupt``; the model turn and the queued speech are cancelled here.

Install: ``pip install -e '.[voice]'`` (speech recognition) and ``openatlas ev voice-setup``
(MeloTTS in its own Python 3.11 venv - its pinned libraries don't install on newer Pythons).
Without the voice worker the page uses the browser's own en-AU voice if it has one; without
faster-whisper the mic explains what to install. Model loads go through
``runtime.limits.cached_model`` (once, never per call).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from openatlas.logger import get_logger
from openatlas.runtime import limits
from openatlas.web.ev_routes import _post

log = get_logger("openatlas.ev.voice")

IN_RATE = 16000
FRAME_MS = 20
END_SILENCE_MS = int(os.getenv("OPENATLAS_EV_END_SILENCE_MS", "450"))
MIN_SPEECH_MS = 250
MAX_UTTERANCE_S = 30
VOICE = os.getenv("OPENATLAS_EV_VOICE", "EN-AU")


# ------------------------------------------------------------------ engines (overridable in tests)
class WhisperSTT:
    def __init__(self) -> None:
        from faster_whisper import WhisperModel  # type: ignore

        gpu = limits.gpu_available()
        name = os.getenv("OPENATLAS_EV_STT_MODEL") or ("small.en" if gpu else "base.en")
        self.name = name
        self.model = WhisperModel(name, device="cuda" if gpu else "cpu",
                                  compute_type="float16" if gpu else "int8")

    def transcribe(self, pcm: bytes) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                            condition_on_previous_text=False, without_timestamps=True)
        return " ".join(s.text.strip() for s in segments).strip()


class SidecarTTS:
    """MeloTTS EN-AU running in its own venv (see ``tts_worker.py``), kept warm between sentences."""

    def __init__(self) -> None:
        import subprocess

        py = sidecar_python()
        if not py:
            raise RuntimeError("E.V's voice isn't set up yet - run: openatlas ev voice-setup")
        self.proc = subprocess.Popen([str(py), str(Path(__file__).with_name("tts_worker.py"))],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env={**os.environ, "OPENATLAS_EV_VOICE": VOICE})
        first = json.loads(self.proc.stdout.readline() or b"{}")
        if not first.get("ready"):
            raise RuntimeError(f"E.V's voice failed to start: {first.get('error', 'no answer')}")
        self.lock = threading.Lock()
        self.n = 0
        self.rate = 44100

    def synth(self, text: str, speed: float = 1.0) -> bytes:
        with self.lock:
            self.n += 1
            self.proc.stdin.write((json.dumps({"id": self.n, "text": text, "speed": speed}) + "\n").encode())
            self.proc.stdin.flush()
            head = json.loads(self.proc.stdout.readline() or b"{}")
            if "error" in head or "bytes" not in head:
                raise RuntimeError(head.get("error", "voice worker stopped"))
            self.rate = int(head["rate"])
            return self.proc.stdout.read(int(head["bytes"]))

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()


def voice_dir() -> Path:
    from openatlas.ev import db

    return db.ev_dir() / "voice-venv"


def sidecar_python() -> Optional[Path]:
    env = os.getenv("OPENATLAS_EV_TTS_PYTHON")
    if env:
        return Path(env) if Path(env).exists() else None
    py = voice_dir() / "bin" / "python"
    return py if py.exists() else None


def setup_sidecar(log: Callable[[str], None] = print) -> Path:
    """Build the voice venv: Python 3.11/3.10 + MeloTTS (Australian EN-AU) + its dictionary.
    Everything comes from PyPI / GitHub / Hugging Face - free and public, no keys."""
    import shutil
    import subprocess

    base = next((shutil.which(p) for p in ("python3.11", "python3.10") if shutil.which(p)), None)
    if not base:
        raise RuntimeError("MeloTTS needs Python 3.11 or 3.10 beside your main Python. On Fedora: "
                           "sudo dnf install python3.11   then run this again.")
    venv = voice_dir()
    if not (venv / "bin" / "python").exists():
        log(f"creating the voice environment with {base} in {venv}")
        subprocess.run([base, "-m", "venv", str(venv)], check=True)
    py = str(venv / "bin" / "python")
    steps = [
        [py, "-m", "pip", "install", "-U", "pip", "wheel"],
        [py, "-m", "pip", "install", "numpy<2", "torch", "torchaudio"],
        [py, "-m", "pip", "install", "git+https://github.com/myshell-ai/MeloTTS.git"],
        [py, "-m", "unidic", "download"],
    ]
    for cmd in steps:
        log("$ " + " ".join(cmd[1:]))
        subprocess.run(cmd, check=True)
    return Path(py)


STT_FACTORY: Callable[[], Any] = lambda: limits.cached_model("ev-stt", WhisperSTT)  # noqa: E731
TTS_FACTORY: Callable[[], Any] = lambda: limits.cached_model("ev-tts", SidecarTTS)  # noqa: E731


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def status() -> Dict[str, Any]:
    stt, tts = _has("faster_whisper"), sidecar_python() is not None
    return {"stt": {"available": stt, "engine": "faster-whisper",
                    "hint": None if stt else "pip install -e '.[voice]'  (or: pip install faster-whisper)"},
            "tts": {"available": tts, "engine": "MeloTTS", "voice": VOICE,
                    "fallback": None if tts else "browser en-AU voice",
                    "hint": None if tts else "openatlas ev voice-setup  (Australian EN-AU voice; needs: sudo dnf install python3.11)"},
            "end_silence_ms": END_SILENCE_MS}


# ------------------------------------------------------------------ endpointing
class Endpointer:
    """Feeds 20 ms frames; returns the finished utterance's PCM once speech is followed by
    ``END_SILENCE_MS`` of silence."""

    def __init__(self) -> None:
        self.vad = None
        if _has("webrtcvad"):
            import webrtcvad  # type: ignore

            self.vad = webrtcvad.Vad(2)
        self.noise = 300.0
        self.buf = bytearray()
        self.speech_ms = self.silence_ms = 0
        self.in_speech = False

    def is_speech(self, frame: bytes) -> bool:
        if self.vad is not None and len(frame) == IN_RATE * FRAME_MS // 1000 * 2:
            return bool(self.vad.is_speech(frame, IN_RATE))
        samples = memoryview(frame).cast("h") if frame else memoryview(b"").cast("h")
        rms = (sum(x * x for x in samples) / len(samples)) ** 0.5 if len(samples) else 0.0
        speech = rms > max(3 * self.noise, 500)
        if not speech:  # adapt to the room
            self.noise = 0.95 * self.noise + 0.05 * rms
        return speech

    def feed(self, frame: bytes) -> Dict[str, Any]:
        speech = self.is_speech(frame)
        out: Dict[str, Any] = {"speech": speech, "started": False, "utterance": None}
        if speech:
            if not self.in_speech:
                out["started"] = True
            self.in_speech = True
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            self.buf += frame
        elif self.in_speech:
            self.silence_ms += FRAME_MS
            self.buf += frame
            if self.silence_ms >= END_SILENCE_MS:
                if self.speech_ms >= MIN_SPEECH_MS:
                    out["utterance"] = bytes(self.buf)
                self.reset()
        if len(self.buf) > MAX_UTTERANCE_S * IN_RATE * 2:
            out["utterance"] = bytes(self.buf)
            self.reset()
        return out

    def reset(self) -> None:
        self.buf = bytearray()
        self.speech_ms = self.silence_ms = 0
        self.in_speech = False


# ------------------------------------------------------------------ text shaping for speech
_MD = re.compile(r"(\*\*|__|`|#+\s|^\s*[-*]\s)", re.M)


def speakable(text: str) -> str:
    t = re.sub(r"\[\d{1,2}\]", "", text)
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"_\(Local AI note:.*?\)_", "", t, flags=re.S)
    t = _MD.sub("", t)
    t = t.replace("E.V", "Eevee").replace("OpenAtlas", "Open Atlas")
    return re.sub(r"\s+", " ", t).strip()


class SentenceSplitter:
    """Tokens in, speakable sentences out - as early as possible for a fast first sound."""

    def __init__(self, first_min: int = 12, min_len: int = 30, max_len: int = 220) -> None:
        self.buf, self.first, self.min_len, self.max_len, self.first_min = "", True, min_len, max_len, first_min

    def push(self, tok: str) -> List[str]:
        self.buf += tok
        out = []
        while True:
            need = self.first_min if self.first else self.min_len
            m = None
            for mm in re.finditer(r"[.!?…](\s|$)|[,;:]\s(?=\S)", self.buf):
                if mm.end() >= need and (mm.group(0)[0] in ".!?…" or mm.end() >= self.max_len * 0.6):
                    m = mm
                    break
            if not m and len(self.buf) >= self.max_len:
                cut = self.buf.rfind(" ", 0, self.max_len)
                m_end = cut if cut > 0 else self.max_len
            elif m:
                m_end = m.end()
            else:
                return out
            piece, self.buf = self.buf[:m_end].strip(), self.buf[m_end:]
            if speakable(piece):
                out.append(speakable(piece))
                self.first = False

    def flush(self) -> List[str]:
        rest, self.buf = speakable(self.buf), ""
        return [rest] if rest else []


# ------------------------------------------------------------------ one conversation over a socket
class Session:
    def __init__(self, conv_id: Optional[int] = None) -> None:
        self.conv_id = conv_id
        self.ep = Endpointer()
        self.stop = threading.Event()
        self.turn: Optional[asyncio.Task] = None
        self.speaking = False
        self.speak = True
        self.closed = False

    def close(self) -> None:
        self.closed = True
        self.stop.set()
        if self.turn and not self.turn.done():
            self.turn.cancel()

    async def send(self, ws: Any, ev: Dict[str, Any]) -> None:
        if not self.closed:
            await ws.send_text(json.dumps(ev, default=str))

    async def interrupt(self, ws: Any) -> None:
        self.stop.set()
        if self.turn and not self.turn.done():
            self.turn.cancel()
            try:
                await self.turn
            except (asyncio.CancelledError, Exception):
                pass
        self.speaking = False
        await self.send(ws, {"type": "audio_stop"})

    async def run(self, ws: Any) -> None:
        st = status()
        tts_ok = st["tts"]["available"] or TTS_FACTORY is not _default_tts
        stt_ok = st["stt"]["available"] or STT_FACTORY is not _default_stt
        await self.send(ws, {"type": "ready", "stt": stt_ok, "tts": "server" if tts_ok else "browser",
                             "voice": VOICE, "in_rate": IN_RATE, "hint": st["stt"]["hint"] or st["tts"]["hint"]})
        loop = asyncio.get_running_loop()
        if stt_ok:
            await loop.run_in_executor(None, STT_FACTORY)  # warm up once so the first reply is fast
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                if not stt_ok:
                    continue
                data = msg["bytes"]
                step = IN_RATE * FRAME_MS // 1000 * 2
                for i in range(0, len(data) - step + 1, step):
                    r = self.ep.feed(data[i:i + step])
                    if r["started"]:
                        await self.send(ws, {"type": "vad", "speech": True})
                        if self.speaking or (self.turn and not self.turn.done()):
                            await self.interrupt(ws)  # barge-in from the server side too
                    if r["utterance"]:
                        await self.send(ws, {"type": "vad", "speech": False})
                        self.turn = asyncio.create_task(self.handle(ws, r["utterance"], None))
            elif msg.get("text"):
                cmd = json.loads(msg["text"])
                if cmd.get("type") == "interrupt":
                    await self.interrupt(ws)
                elif cmd.get("type") == "config":
                    self.speak = bool(cmd.get("speak", True))
                    self.conv_id = cmd.get("conv_id") or self.conv_id
                elif cmd.get("type") == "text" and cmd.get("text"):
                    await self.interrupt(ws)
                    self.turn = asyncio.create_task(self.handle(ws, None, str(cmd["text"])))

    async def handle(self, ws: Any, pcm: Optional[bytes], typed: Optional[str]) -> None:
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        timings: Dict[str, Any] = {}
        if pcm is not None:
            stt = await loop.run_in_executor(None, STT_FACTORY)
            text = await loop.run_in_executor(None, stt.transcribe, pcm)
            timings["stt_ms"] = round((time.monotonic() - t0) * 1000)
            await self.send(ws, {"type": "transcript", "text": text, "ms": timings["stt_ms"]})
            if not text or len(text.strip(" .")) < 2:
                return
        else:
            text = typed or ""
        self.stop = threading.Event()
        stop = self.stop
        q: asyncio.Queue = asyncio.Queue()
        from openatlas.ev import agent, persona

        def work() -> None:
            try:
                for ev in agent.respond(self.conv_id, text, stop=stop, voice=True):
                    if ev["type"] != "_result":
                        _post(loop, q, ev)
            except Exception as exc:
                _post(loop, q, {"type": "notice", "level": "error", "text": str(exc)})
            finally:
                _post(loop, q, None)

        threading.Thread(target=work, daemon=True, name="ev-voice-turn").start()
        split = SentenceSplitter()
        speech_q: asyncio.Queue = asyncio.Queue()
        speed = persona.settings()["voice_speed"]
        use_server_tts = self.speak and (status()["tts"]["available"] or TTS_FACTORY is not _default_tts)

        async def speaker() -> None:
            tts = await loop.run_in_executor(None, TTS_FACTORY) if use_server_tts else None
            while True:
                sentence = await speech_q.get()
                if sentence is None or stop.is_set():
                    break
                if tts is None:  # the browser speaks it with its en-AU voice
                    await self.send(ws, {"type": "say", "text": sentence})
                    continue
                pcm_out = await loop.run_in_executor(None, tts.synth, sentence, speed)
                if stop.is_set():
                    break
                if "first_audio_ms" not in timings:
                    timings["first_audio_ms"] = round((time.monotonic() - t0) * 1000)
                    await self.send(ws, {"type": "timings", **timings})
                self.speaking = True
                await self.send(ws, {"type": "audio_start", "text": sentence, "rate": getattr(tts, "rate", 24000)})
                for i in range(0, len(pcm_out), 16384):
                    if stop.is_set():
                        break
                    await ws.send_bytes(pcm_out[i:i + 16384])
                await self.send(ws, {"type": "audio_end"})
            self.speaking = False

        speak_task = asyncio.create_task(speaker()) if self.speak else None
        try:
            while True:
                ev = await q.get()
                if ev is None:
                    break
                if ev["type"] == "start":
                    self.conv_id = ev["conv_id"]
                if ev["type"] == "token":
                    timings.setdefault("first_token_ms", round((time.monotonic() - t0) * 1000))
                    for s in split.push(ev["text"]):
                        await speech_q.put(s)
                if ev["type"] == "done":
                    for s in split.flush():
                        await speech_q.put(s)
                    ev = {**ev, "timings": timings}
                await self.send(ws, ev)
        finally:
            await speech_q.put(None)
            if speak_task:
                try:
                    await speak_task
                except asyncio.CancelledError:
                    pass
            if "first_audio_ms" in timings or "first_token_ms" in timings:
                await self.send(ws, {"type": "timings", **timings,
                                     "total_ms": round((time.monotonic() - t0) * 1000)})


_default_stt, _default_tts = STT_FACTORY, TTS_FACTORY
