"""One translation direction = one Gemini Live session, kept alive across
go_away, errors and closes with the latest session-resumption handle."""
from __future__ import annotations

import asyncio
import contextlib
import statistics
import time
from dataclasses import dataclass, field

from google.genai import types

from .pairing import Pairer
from .vad import VAD, audible

DEFAULT_MODEL = "gemini-3.5-live-translate-preview"
FALLBACK_MODEL = "gemini-3.8-live"
# Business register for Japanese output (fallback model only; see docs/REGISTER.md).
KEIGO_INSTRUCTION = ("あなたは同時通訳者です。聞こえた発話を日本語のビジネス敬語に翻訳してください。"
                     "必ずです・ます調を使い、謙譲語・尊敬語を適切に使い分けてください。"
                     "タメ口や砕けた表現は禁止です。翻訳のみを出力し、説明・挨拶・返答は一切しないでください。"
                     "発話がすでに日本語の場合は何も出力しないでください。")
LANG_NAMES = {"ja": "Japanese", "en": "English", "zh": "Chinese", "ko": "Korean",
              "es": "Spanish", "fr": "French", "de": "German", "hi": "Hindi", "ta": "Tamil"}
SENTENCE_END = tuple(".?!。？！")


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code.split("-")[0].lower(), code)


def build_config(model: str, target: str, handle: str | None,
                 instruction: str | None = None, extra: dict | None = None) -> types.LiveConnectConfig:
    """`instruction` replaces the generic translator prompt on non-translate
    models. On a translate model it is added next to translation_config (an
    experiment: Live Translate documents no system instruction). `extra` adds
    LiveConnectConfig fields (e.g. realtime_input_config) for experiments."""
    kw = dict(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        session_resumption=types.SessionResumptionConfig(handle=handle),
    )
    if "translate" in model:
        kw["translation_config"] = types.TranslationConfig(target_language_code=target, echo_target_language=False)
        if instruction:
            kw["system_instruction"] = instruction
    elif instruction:
        kw["system_instruction"] = instruction
    else:
        name = lang_name(target)
        kw["system_instruction"] = (f"You are a translator. Translate everything you hear into {name}. "
                                    f"Output only the translation, nothing else. "
                                    f"If the speech is already in {name}, stay silent.")
    kw.update(extra or {})
    return types.LiveConnectConfig(**kw)


# USD per 1M audio tokens (input, output), by model. The one place prices live.
AUDIO_RATES_PER_M = {
    "gemini-3.5-live-translate-preview": (3.50, 21.00),
    "gemini-3.8-live": (3.00, 12.00),
}


def audio_rates(model: str) -> tuple[tuple[float, float], bool]:
    """((in, out) USD per 1M audio tokens, known). Unknown models are priced
    as Live Translate."""
    if model in AUDIO_RATES_PER_M:
        return AUDIO_RATES_PER_M[model], True
    return AUDIO_RATES_PER_M[DEFAULT_MODEL], False


def modality_counts(details) -> dict:
    out = {}
    for d in details or []:
        m = str(getattr(d, "modality", "")).split(".")[-1].upper()
        out[m] = out.get(m, 0) + (getattr(d, "token_count", 0) or 0)
    return out


UTTERANCE_QUIET_S = 1.5  # close an utterance this long after its last event, once speech has ended


@dataclass
class Utterance:
    """One spoken turn: from VAD onset (or the first transcript when there was
    none) until the next onset or UTTERANCE_QUIET_S of quiet. Times are on the
    Direction clock (monotonic)."""
    onset: float | None
    first: float
    last: float
    audio_at: float | None = None
    src_final_at: float | None = None
    dst_final_at: float | None = None
    src: list[str] = field(default_factory=list)
    dst: list[str] = field(default_factory=list)
    seq: int = 0  # numbers utterances within a direction; pairing never folds text across them

    def touch(self, now: float) -> None:
        self.last = max(self.last, now)

    def latency(self) -> dict:
        o2a = None if self.onset is None or self.audio_at is None else round((self.audio_at - self.onset) * 1000)
        s2d = None
        if self.src_final_at is not None and self.dst_final_at is not None and self.dst_final_at >= self.src_final_at:
            s2d = round((self.dst_final_at - self.src_final_at) * 1000)
        return {"onset_to_audio_ms": o2a, "src_final_to_dst_final_ms": s2d}

    @property
    def has_content(self) -> bool:
        return bool(self.src or self.dst or self.audio_at is not None)


class Direction:
    """Pumps 16 kHz chunks from in_q into the session and puts 24 kHz audio
    bytes from the model on out_q. `connect(model=, config=)` must return an
    async context manager yielding a session (client.aio.live.connect)."""

    def __init__(self, label, src, dst, model, in_q, out_q=None, *, connect,
                 is_muted=lambda: False, out=print, dump=None, backoff=(1, 2, 4), emit=None,
                 vad: VAD | None = None, on_utterance=None, clock=time.monotonic, instruction=None,
                 on_row=None, live_options: dict | None = None):
        self.label, self.src, self.dst, self.model = label, src, dst, model
        self.in_q, self.out_q, self.connect = in_q, out_q, connect
        self.is_muted, self.out, self.dump, self.backoff = is_muted, out, dump, backoff
        self.instruction = instruction
        self.live_options = live_options  # extra LiveConnectConfig fields
        self.emit = emit  # JSON mode: structured events replace the plain lines
        self.vad = vad if vad is not None else VAD(gate=False)
        self.on_utterance = on_utterance  # (dir, Utterance) when an utterance closes
        self.clock = clock
        self.utt: Utterance | None = None
        self._utt_seq = 0
        # Source/translation rows, paired by timing (kana/pairing.py); on_row(dir, Row)
        # receives each row once it can no longer change (saved transcripts).
        self.pairer = Pairer(on_row=(lambda r: on_row(label.lower(), r)) if on_row else None)
        self.latencies: list[int] = []
        # Server-reported tokens. Every usage_metadata message is a delta: Live
        # Translate reports each 1-2 s of streaming, the general model each turn
        # (verified 2026-11-12, docs/ENGINE.md "Cost").
        self.tokens = {"in_audio": 0, "out_audio": 0, "in_text": 0, "out_text": 0}
        self.rates, self._rate_known = audio_rates(model)
        self._rate_warned = False
        self.prefix = f"[{label} {src}->{dst}]"
        self.handle: str | None = None
        self.session = None
        self.connects = 0
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.audio_bytes = 0
        self.in_text: list[str] = []
        self.out_text: list[str] = []
        self._buf = {"in": "", "out": ""}
        self._fails = 0

    def log(self, msg: str) -> None:
        if self.emit is None:
            self.out(f"{self.prefix} ({msg})")

    def _session(self, state: str, detail: str = "") -> None:
        if self.emit is not None:
            self.emit("session", dir=self.label.lower(), state=state, detail=detail)

    async def run(self) -> None:
        pump = asyncio.create_task(self._pump())
        try:
            while True:
                reason = "closed"
                try:
                    config = build_config(self.model, self.dst, self.handle, self.instruction, self.live_options)
                    async with self.connect(model=self.model, config=config) as s:
                        self.connects += 1
                        if self.connects > 1:
                            self.log("reconnected" + (" (resumed)" if self.handle else ""))
                        self.session = s
                        self._session("connected")
                        reason = await self._receive(s)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # network, server, auth: retry with backoff
                    reason = f"error: {e!r}"[:200]
                finally:
                    self.session = None
                    self._flush()
                if reason == "go_away":
                    self._session("reconnecting", "go_away")
                    continue  # reconnect at once with the latest handle
                delay = self.backoff[min(self._fails, len(self.backoff) - 1)]
                self._fails += 1
                self.log(f"{reason}; reconnecting in {delay}s")
                self._session("reconnecting", reason if reason.startswith("error") else "")
                await asyncio.sleep(delay)
        finally:
            self._session("closed")
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
            self._flush()
            self.close_utterance()
            self._seal(force=True)

    async def _pump(self) -> None:
        """Always drains in_q so capture never blocks; only sends while a
        session is up and the direction is not muted."""
        was_muted = False
        while True:
            chunk = await self.in_q.get()
            muted, s = self.is_muted(), self.session
            self.maybe_close_utterance()
            if muted:
                self.vad.reset()  # muted chunks are neither gated nor speech
                if s is not None and not was_muted:  # let the model finish the half-said sentence
                    with contextlib.suppress(Exception):
                        await s.send_realtime_input(audio_stream_end=True)
                was_muted = muted
                continue
            was_muted = muted
            dec = self.vad.push(chunk)
            if s is None:
                continue  # drained, never queued for later: no chunk is sent twice
            if dec.onset:
                self._onset()
            try:
                for c in dec.send:
                    await s.send_realtime_input(audio=types.Blob(data=c, mime_type="audio/pcm;rate=16000"))
                    self.chunks_sent += 1
                    self.bytes_sent += len(c)
                if dec.end:
                    await s.send_realtime_input(audio_stream_end=True)
            except Exception:
                pass  # the receiver sees the broken connection and reconnects

    # --- utterances: latency and saved transcripts ---------------------------

    def _onset(self) -> None:
        now = self.clock()
        self.close_utterance()
        self._utt_seq += 1
        self.utt = Utterance(onset=now, first=now, last=now, seq=self._utt_seq)

    def _current(self) -> Utterance:
        if self.utt is None:  # a transcript or audio with no onset seen (e.g. right after a reconnect)
            now = self.clock()
            self._utt_seq += 1
            self.utt = Utterance(onset=None, first=now, last=now, seq=self._utt_seq)
        return self.utt

    def maybe_close_utterance(self) -> None:
        u = self.utt
        if u is not None and not self.vad.speaking and self.clock() - u.last >= UTTERANCE_QUIET_S:
            self._flush()  # text without a sentence end still belongs to this utterance
            self.close_utterance()
        self._seal()

    def _seal(self, force: bool = False) -> None:
        for op in self.pairer.seal(self.clock(), force=force):
            self._emit_transcript(op)

    def _emit_transcript(self, op: dict) -> None:
        if self.emit is not None:
            self.emit("transcript", dir=self.label.lower(), **op, final=True)

    def close_utterance(self) -> None:
        u, self.utt = self.utt, None
        if u is None or not u.has_content:
            return
        lat = u.latency()
        if lat["onset_to_audio_ms"] is not None:
            self.latencies.append(lat["onset_to_audio_ms"])
        if self.emit is not None:
            self.emit("latency", dir=self.label.lower(), **lat)
        if self.on_utterance is not None:
            self.on_utterance(self.label.lower(), u)

    def latency_ms(self) -> int | None:
        return round(statistics.median(self.latencies)) if self.latencies else None

    async def _receive(self, s) -> str:
        while True:  # receive() ends after each model turn
            got = False
            async for r in s.receive():
                got = True
                self._fails = 0
                upd = getattr(r, "session_resumption_update", None)
                if upd and upd.resumable and upd.new_handle:
                    self.handle = upd.new_handle
                ga = getattr(r, "go_away", None)
                if ga:
                    self.log(f"go_away, time left {ga.time_left}; reconnecting")
                    return "go_away"
                um = getattr(r, "usage_metadata", None)
                if um:
                    self._usage(um)
                sc = getattr(r, "server_content", None)
                if sc:
                    self._server_content(sc)
            if not got:
                return "session closed"

    def _usage(self, um) -> None:
        p, q = modality_counts(um.prompt_tokens_details), modality_counts(um.response_tokens_details)
        if not p and um.prompt_token_count:  # no breakdown: count it as audio (the billed worst case)
            p = {"AUDIO": um.prompt_token_count}
        if not q and um.response_token_count:
            q = {"AUDIO": um.response_token_count}
        add = {"in_audio": p.get("AUDIO", 0), "out_audio": q.get("AUDIO", 0),
               "in_text": p.get("TEXT", 0), "out_text": q.get("TEXT", 0)}
        if not any(add.values()):
            return
        for k, v in add.items():
            self.tokens[k] += v
        if self.emit is not None:
            if not self._rate_known and not self._rate_warned:
                self._rate_warned = True
                self.emit("error", fatal=False,
                          text=f"no audio token rate for model {self.model}; assuming {DEFAULT_MODEL} rates "
                               f"(${self.rates[0]:.2f} in / ${self.rates[1]:.2f} out per 1M)")
            self.emit("usage", dir=self.label.lower(), model=self.model, in_audio_tokens=self.tokens["in_audio"],
                      out_audio_tokens=self.tokens["out_audio"], usd=self.usd(),
                      in_text_tokens=self.tokens["in_text"])

    def usd(self) -> float:
        rate_in, rate_out = self.rates
        return round((self.tokens["in_audio"] * rate_in + self.tokens["out_audio"] * rate_out) / 1e6, 6)

    def _server_content(self, sc) -> None:
        if sc.input_transcription and sc.input_transcription.text:
            self._add("in", sc.input_transcription.text)
        if sc.output_transcription and sc.output_transcription.text:
            self._add("out", sc.output_transcription.text)
        if sc.model_turn:
            for p in sc.model_turn.parts or []:
                if p.inline_data and p.inline_data.data:
                    data = p.inline_data.data
                    self.audio_bytes += len(data)  # all of it: the billing basis
                    if audible(data):  # the model streams silence between turns
                        u, now = self._current(), self.clock()
                        if u.audio_at is None:
                            u.audio_at = now
                        u.touch(now)
                    if self.out_q is not None:
                        self.out_q.put_nowait(data)
                    if self.dump is not None:
                        self.dump.writeframes(data)
        if getattr(sc, "turn_complete", False):
            self._flush()

    def _add(self, kind: str, text: str) -> None:
        (self.in_text if kind == "in" else self.out_text).append(text)
        self._buf[kind] += text
        if self._buf[kind].rstrip().endswith(SENTENCE_END):
            self._flush(kind)

    def _flush(self, *kinds: str) -> None:
        for kind in kinds or ("in", "out"):
            text = self._buf[kind].strip()
            self._buf[kind] = ""
            if not text:
                continue
            u, now = self._current(), self.clock()
            u.touch(now)
            if kind == "in":
                u.src.append(text)
                u.src_final_at = now
            else:
                u.dst.append(text)
                u.dst_final_at = now
            pair = self.pairer.src if kind == "in" else self.pairer.dst
            ops = pair(text, now, u.seq)
            if self.emit is not None:
                for op in ops:
                    self._emit_transcript(op)
            else:
                self.out(f"{self.prefix} {'=> ' if kind == 'out' else ''}{text}")

    def transcript(self, kind: str) -> str:
        return "".join(self.in_text if kind == "in" else self.out_text)
