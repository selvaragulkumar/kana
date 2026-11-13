"""One translation direction on OpenAI's realtime translation model
(gpt-realtime-translate) instead of Gemini Live Translate.

The websocket is wrapped so it looks like a Gemini Live session to `Direction`:
`send_realtime_input(audio=Blob)` resamples our 16 kHz chunks to the 24 kHz PCM16 the
API takes, and `receive()` yields objects shaped like the Gemini SDK's responses
(`server_content.model_turn` / `output_transcription` / `input_transcription`). So the
voice gate, utterances, latency, pairing and transcripts are the same code for both
providers.

What differs (OpenAI translation guide and server-event reference, 2026-11):
- one session = one target language (`session.audio.output.language`); the source
  language is detected; no instruction, no voice choice, no register control;
- there is no turn lifecycle and no stream-end message: `audio_stream_end` is a no-op
  and the model decides when it has heard enough;
- no session resumption: a reconnect starts a fresh session;
- no usage or token counts are reported. The price is per minute of audio sent, so
  `usd()` is computed from what kana sent and marked as an estimate (`est`).

The API key is passed only in the Authorization header; it is never logged.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from types import SimpleNamespace as NS

import numpy as np

from .audio import IN_RATE, OUT_RATE, resample
from .session import AUDIO_RATES_PER_MIN, Direction

OPENAI_MODEL = "gpt-realtime-translate"
OPENAI_URL = "wss://api.openai.com/v1/realtime/translations"
# Source-language transcript (kind "src"); the model named in OpenAI's translation guide.
TRANSCRIBE_MODEL = "gpt-realtime-whisper"
HANDSHAKE_TIMEOUT_S = 10.0
CLOSE_TIMEOUT_S = 2.0


class OpenAIError(RuntimeError):
    """An `error` event from the server. Raised out of receive(), so the Direction
    reconnects with backoff, the same as a Gemini network or server error."""


def _response(**sc) -> NS:
    base = dict(input_transcription=None, output_transcription=None, model_turn=None, turn_complete=False)
    base.update(sc)
    return NS(session_resumption_update=None, go_away=None, usage_metadata=None, server_content=NS(**base))


def _error_text(ev: dict) -> str:
    err = ev.get("error") or {}
    code = err.get("code") or err.get("type") or "error"
    return f"{code}: {err.get('message', '')}".strip()[:200]


class TranslateSession:
    """A connected translation websocket, presented as a Gemini Live session."""

    def __init__(self, ws):
        self.ws = ws
        self.closed = False

    async def send_realtime_input(self, audio=None, audio_stream_end=None, **_) -> None:
        if audio is None:
            return  # audio_stream_end: the translation API has no such message
        x = np.frombuffer(audio.data, dtype="<i2")
        pcm24 = resample(x, IN_RATE, OUT_RATE).astype("<i2").tobytes()
        await self.ws.send(json.dumps({"type": "session.input_audio_buffer.append",
                                       "audio": base64.b64encode(pcm24).decode("ascii")}))

    async def receive(self):
        """Yields Gemini-shaped responses until the socket closes or the session ends.
        An abnormal close raises (websockets' ConnectionClosedError)."""
        if self.closed:
            return
        async for raw in self.ws:
            ev = json.loads(raw)
            t = ev.get("type", "")
            if t == "session.output_audio.delta":
                data = base64.b64decode(ev.get("delta") or "")
                rate = ev.get("sample_rate") or OUT_RATE
                if rate != OUT_RATE:  # documented default 24 kHz; guard against a change
                    data = resample(np.frombuffer(data, dtype="<i2"), rate, OUT_RATE).astype("<i2").tobytes()
                if data:
                    yield _response(model_turn=NS(parts=[NS(inline_data=NS(data=data))]))
            elif t == "session.output_transcript.delta":
                if ev.get("delta"):
                    yield _response(output_transcription=NS(text=ev["delta"]))
            elif t == "session.input_transcript.delta":
                if ev.get("delta"):
                    yield _response(input_transcription=NS(text=ev["delta"]))
            elif t == "error":
                raise OpenAIError(_error_text(ev))
            elif t == "session.closed":
                self.closed = True
                return
        self.closed = True


async def _await_event(ws, wanted: str) -> dict:
    async for raw in ws:
        ev = json.loads(raw)
        if ev.get("type") == wanted:
            return ev
        if ev.get("type") == "error":
            raise OpenAIError(_error_text(ev))
    raise ConnectionError(f"socket closed before {wanted}")


def make_connect(api_key: str, url: str = OPENAI_URL, ws_connect=None, transcribe: bool = True):
    """connect(model=, config=) for Direction, as an async context manager. `config`
    is OpenAIDirection._config(): {"language": "ja"}."""
    if ws_connect is None:
        import websockets
        ws_connect = websockets.connect

    @contextlib.asynccontextmanager
    async def connect(model: str, config: dict):
        ws = await ws_connect(f"{url}?model={model}", additional_headers={"Authorization": f"Bearer {api_key}"},
                              max_size=None)
        try:
            session: dict = {"audio": {"output": {"language": config["language"]}}}
            if transcribe:
                session["audio"]["input"] = {"transcription": {"model": TRANSCRIBE_MODEL}}
            async with asyncio.timeout(HANDSHAKE_TIMEOUT_S):
                await _await_event(ws, "session.created")
                await ws.send(json.dumps({"type": "session.update", "session": session}))
                await _await_event(ws, "session.updated")
            yield TranslateSession(ws)
        finally:
            with contextlib.suppress(Exception):  # best effort: ask the server to end, then close
                async with asyncio.timeout(CLOSE_TIMEOUT_S):
                    await ws.send(json.dumps({"type": "session.close"}))
                    await ws.close()

    return connect


class OpenAIDirection(Direction):
    """A Direction on gpt-realtime-translate. Same queues, events and transcripts;
    cost is per minute of audio sent, reported as an estimate."""

    usd_is_estimate = True
    USAGE_EVERY_BYTES = IN_RATE * 2  # one `usage` event per second of audio sent

    def __init__(self, *a, **kw):
        if kw.get("instruction"):
            raise ValueError("gpt-realtime-translate takes no instruction (no --register business)")
        super().__init__(*a, **kw)
        self.rate_per_min = AUDIO_RATES_PER_MIN.get(self.model, AUDIO_RATES_PER_MIN[OPENAI_MODEL])
        self._rate_known = True
        self._usage_at = 0

    def _config(self) -> dict:
        return {"language": self.dst.split("-")[0].lower()}

    def usd(self) -> float:
        return round(self.bytes_sent / (IN_RATE * 2) / 60 * self.rate_per_min, 6)

    def _on_sent(self) -> None:
        if self.emit is None or self.bytes_sent - self._usage_at < self.USAGE_EVERY_BYTES:
            return
        self._usage_at = self.bytes_sent
        self.emit("usage", dir=self.label.lower(), model=self.model,
                  sent_s=round(self.bytes_sent / (IN_RATE * 2), 1), usd=self.usd(), est=True)
