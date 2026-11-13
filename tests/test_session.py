import asyncio
import contextlib
from types import SimpleNamespace as NS

from kana.session import Direction, build_config


def resp(**kw):
    base = dict(session_resumption_update=None, go_away=None, server_content=None)
    base.update(kw)
    return NS(**base)


def content(inp=None, outp=None, audio=None, turn_complete=False):
    return NS(
        input_transcription=NS(text=inp) if inp else None,
        output_transcription=NS(text=outp) if outp else None,
        model_turn=NS(parts=[NS(inline_data=NS(data=audio))]) if audio else None,
        turn_complete=turn_complete,
    )


class FakeSession:
    def __init__(self, turns, block_after=False):
        self.turns = list(turns)  # each turn = list of responses for one receive()
        self.block_after = block_after
        self.sent = []

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def receive(self):
        if self.turns:
            for r in self.turns.pop(0):
                yield r
        elif self.block_after:
            await asyncio.Event().wait()


def make_connect(sessions, gate=None):
    handles = []

    @contextlib.asynccontextmanager
    async def connect(model, config):
        handles.append(config.session_resumption.handle)
        if gate is not None and len(handles) > 1:
            await gate.wait()
        yield sessions.pop(0)

    return connect, handles


async def wait_for(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.01)


def test_build_config_translate_vs_fallback():
    c = build_config("gemini-3.5-live-translate-preview", "ja", "h")
    assert c.translation_config.target_language_code == "ja"
    assert c.translation_config.echo_target_language is False
    assert c.session_resumption.handle == "h"
    f = build_config("gemini-3.8-live", "ja", None)
    assert f.translation_config is None and "Japanese" in f.system_instruction


async def test_direction_end_to_end_with_fake_session():
    s1 = FakeSession([[
        resp(session_resumption_update=NS(resumable=True, new_handle="h1")),
        resp(server_content=content(inp="こんにちは。")),
        resp(server_content=content(outp="Hello,")),
        resp(server_content=content(outp=" nice weather.", audio=b"\x01\x00" * 100)),
        resp(server_content=content(audio=b"\x02\x00" * 50, turn_complete=True)),
    ], [
        resp(session_resumption_update=NS(resumable=True, new_handle="h2")),
        resp(go_away=NS(time_left="10s")),
    ]], block_after=True)
    s2 = FakeSession([], block_after=True)
    gate = asyncio.Event()
    connect, handles = make_connect([s1, s2], gate)
    in_q, out_q, lines = asyncio.Queue(), asyncio.Queue(), []
    d = Direction("IN", "ja", "en", "gemini-3.5-live-translate-preview", in_q, out_q,
                  connect=connect, out=lines.append, backoff=(0.01,))
    task = asyncio.create_task(d.run())
    try:
        # first session ends with go_away; second connect waits on the gate
        await wait_for(lambda: len(handles) == 2)
        assert handles == [None, "h2"]  # reconnect used the latest handle
        assert out_q.qsize() == 2 and d.audio_bytes == 300
        assert "[IN ja->en] こんにちは。" in lines
        assert "[IN ja->en] => Hello, nice weather." in lines
        assert any("go_away" in l for l in lines)

        # disconnected: the input queue keeps draining, nothing is sent
        for _ in range(5):
            in_q.put_nowait(b"\0" * 3200)
        await wait_for(lambda: in_q.qsize() == 0)
        assert d.chunks_sent == 0 and s2.sent == []

        gate.set()
        await wait_for(lambda: d.session is s2)
        for _ in range(3):
            in_q.put_nowait(b"\0" * 3200)
        await wait_for(lambda: len(s2.sent) == 3)
        blob = s2.sent[0]["audio"]
        assert blob.mime_type == "audio/pcm;rate=16000" and len(blob.data) == 3200
        assert d.connects == 2
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_muted_direction_sends_nothing_and_ends_stream():
    muted = [False]
    s = FakeSession([], block_after=True)
    connect, _ = make_connect([s])
    in_q = asyncio.Queue()
    d = Direction("OUT", "en", "ja", "m-translate", in_q, connect=connect,
                  is_muted=lambda: muted[0], out=lambda *_: None)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        in_q.put_nowait(b"\0" * 3200)
        await wait_for(lambda: len(s.sent) == 1)
        muted[0] = True
        for _ in range(3):
            in_q.put_nowait(b"\0" * 3200)
        await wait_for(lambda: in_q.qsize() == 0)
        await asyncio.sleep(0.02)
        assert s.sent[1:] == [{"audio_stream_end": True}] and d.chunks_sent == 1
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_error_triggers_backoff_and_retry():
    calls = []

    @contextlib.asynccontextmanager
    async def connect(model, config):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("boom")
        yield FakeSession([], block_after=True)

    lines = []
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect,
                  out=lines.append, backoff=(0.01,))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.connects == 1)
        assert len(calls) == 2 and any("boom" in l for l in lines)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def test_build_config_instruction_on_both_model_kinds():
    from kana.session import KEIGO_INSTRUCTION
    f = build_config("gemini-3.8-live", "ja", None, KEIGO_INSTRUCTION)
    assert f.translation_config is None and f.system_instruction == KEIGO_INSTRUCTION
    t = build_config("gemini-3.5-live-translate-preview", "ja", None, "x")  # the REGISTER.md experiment
    assert t.translation_config.target_language_code == "ja" and t.system_instruction == "x"


def test_register_modes_pick_models_and_configs():
    from kana.__main__ import direction_models, parse_args
    from kana.session import FALLBACK_MODEL, KEIGO_INSTRUCTION

    def configs(argv):
        a = parse_args(argv)
        m = direction_models(a)
        return m, {k: build_config(model, dst, None, instr)
                   for (k, (model, instr)), dst in zip(m.items(), (a.in_lang, a.out_lang))}

    m, c = configs([])  # default register is the default: Live Translate both ways, own voice
    assert m == {"IN": ("gemini-3.5-live-translate-preview", None), "OUT": ("gemini-3.5-live-translate-preview", None)}
    assert c["OUT"].translation_config.target_language_code == "ja" and c["OUT"].system_instruction is None
    assert parse_args([]).register == "default"

    m, c = configs(["--register", "business"])  # opt-in
    assert m["IN"] == ("gemini-3.5-live-translate-preview", None)
    assert m["OUT"] == (FALLBACK_MODEL, KEIGO_INSTRUCTION)
    assert c["IN"].translation_config.target_language_code == "en" and c["IN"].system_instruction is None
    assert c["OUT"].translation_config is None and "ビジネス敬語" in c["OUT"].system_instruction

    m, _ = configs(["--register", "business", "--in", "ja", "--out", "en"])  # keigo applies only to Japanese output
    assert m["OUT"] == ("gemini-3.5-live-translate-preview", None)
    m, _ = configs(["--register", "business", "--model", "gemini-3.8-live"])  # an explicit general model keeps its name
    assert m == {"IN": ("gemini-3.8-live", None), "OUT": ("gemini-3.8-live", KEIGO_INSTRUCTION)}


# --- keepalive while the voice gate is closed ---------------------------------

class StepClock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


async def _feed(d, in_q, clock, chunks, start, step=0.1):
    """Feeds chunks one at a time, each at its own clock time; returns the clock
    times at which a keepalive was sent."""
    at = []
    for k, c in enumerate(chunks):
        clock.t = round(start + k * step, 3)
        before = d.keepalives
        in_q.put_nowait(c)
        await wait_for(lambda: in_q.empty())
        for _ in range(3):  # let the pump finish this chunk
            await asyncio.sleep(0)
        if d.keepalives > before:
            at.append(clock.t)
    return at


async def _gated_direction(muted=False, hangover_ms=2000):
    from kana.vad import VAD
    from tests.test_events import Rec
    s = FakeSession([], block_after=True)
    connect, _ = make_connect([s])
    in_q, clock, rec = asyncio.Queue(), StepClock(), Rec()
    d = Direction("IN", "ja", "en", "m-translate", in_q, connect=connect, emit=rec, clock=clock,
                  is_muted=lambda: muted, vad=VAD(gate=True, hangover_ms=hangover_ms), keepalive_s=1.0)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: d.session is s)
    return d, s, in_q, clock, rec, task


async def _stop(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_keepalive_one_silence_chunk_per_window_while_gated():
    from kana.session import KEEPALIVE_S
    from tests.test_vad import SIL
    assert KEEPALIVE_S == 20.0
    d, s, in_q, clock, rec, task = await _gated_direction()
    try:
        at = await _feed(d, in_q, clock, [SIL] * 35, start=100.0)  # 3.4 s of gated silence
        assert at == [101.0, 102.0, 103.0]  # one per 1 s window, counted from the first chunk
        assert d.keepalives == 3 and d.chunks_sent == 3 and d.bytes_sent == 3 * 3200
        assert len(s.sent) == 3 and all(k["audio"].data == bytes(3200) for k in s.sent)
        assert s.sent[0]["audio"].mime_type == "audio/pcm;rate=16000"
        assert d.utt is None and d._utt_seq == 0  # not speech: no onset, no utterance
    finally:
        await _stop(task)
    assert not rec.of("latency") and not rec.of("transcript")


async def test_keepalive_while_muted_is_silence_never_the_microphone():
    from tests.test_vad import SIL, tone
    d, s, in_q, clock, rec, task = await _gated_direction(muted=True)
    try:
        await _feed(d, in_q, clock, [tone()] * 50, start=100.0)  # 5 s of speech into a muted direction
        assert d.keepalives == 4 and d.bytes_sent == 4 * 3200
        assert s.sent[0] == {"audio_stream_end": True}  # the mute's own stream end, once
        assert all(k["audio"].data == bytes(3200) for k in s.sent[1:])  # zeros only, no mic audio
        assert d.utt is None and d._utt_seq == 0
    finally:
        await _stop(task)


async def test_speech_resets_the_keepalive_clock():
    from tests.test_vad import SIL, tone
    d, s, in_q, clock, rec, task = await _gated_direction(hangover_ms=200)
    try:
        # 100.0-100.5 silence, 100.6-101.0 speech, 101.1-101.2 hangover (sent), then silence
        chunks = [SIL] * 6 + [tone(k=k) for k in range(5)] + [SIL] * 25
        at = await _feed(d, in_q, clock, chunks, start=100.0)
        assert d.chunks_sent > d.keepalives > 0
        # the last real chunk went at 101.2, so the first keepalive is 1 s later,
        # not at 101.0 as it would be counting from the start of the silence
        assert at == [102.2, 103.2]
    finally:
        await _stop(task)
