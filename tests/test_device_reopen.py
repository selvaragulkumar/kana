"""A capture or playback device that stops mid-call is reopened while the
translation sessions stay up (kana/audio.py watch_streams). A fake sounddevice
module stands in for PortAudio: no real device is opened or unplugged."""
import asyncio
import json

import numpy as np
import pytest

from kana import __main__ as cli
from kana import audio, events
from tests.test_events import Rec, _fast_ticker
from tests.test_session import FakeSession, make_connect, wait_for


class PortAudioError(Exception):
    pass


class CallbackAbort(Exception):
    pass


class FakeSD:
    """sounddevice stand-in. `gone` names devices that currently fail to open (as after
    CoreAudio removed them); `inits` counts PortAudio re-initialisations."""

    CallbackAbort = CallbackAbort
    PortAudioError = PortAudioError

    def __init__(self):
        self.streams = []
        self.gone: set = set()
        self.inits = 0

    def check_input_settings(self, **kw):
        pass

    def check_output_settings(self, **kw):
        pass

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": 48000.0}

    def _terminate(self):
        pass

    def _initialize(self):
        self.inits += 1

    def _stream(self, kind, kw):
        if kw["device"] in self.gone:
            raise PortAudioError(f"Error opening {kind}: device unavailable [PaErrorCode -9996]")
        st = FakeStream(kind, kw)
        self.streams.append(st)
        return st

    def InputStream(self, **kw):
        return self._stream("input", kw)

    def OutputStream(self, **kw):
        return self._stream("output", kw)


class FakeStream:
    def __init__(self, kind, kw):
        self.kind, self.kw = kind, kw
        self.device, self.callback, self.finished_callback = kw["device"], kw["callback"], kw["finished_callback"]
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def abort(self):
        if self.active:
            self.active = False
            self.finished_callback()  # PortAudio calls it on abort too

    def close(self):
        self.closed = True

    def die(self):
        """PortAudio ends the stream on its own (the device went away)."""
        self.active = False
        self.finished_callback()


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSD()
    monkeypatch.setattr(audio, "_sd", lambda: fake)
    return fake


def capture(sd, clock, device=7, name="BlackHole 16ch", resolve=None):
    loop = asyncio.get_running_loop()
    c = audio.Capture(device, asyncio.Queue(maxsize=50), loop, latency="low", block_ms=10, name=name,
                      resolve=resolve, clock=clock)
    c.open()
    return c


def playback(sd, clock, device=4, name="AirPods Pro"):
    p = audio.Playback(device, name=name, clock=clock)
    p.open()
    return p


class Steps:
    """watch_streams' sleep: each await advances the fake clock and lets the test act."""

    def __init__(self, clock, on_step=None):
        self.clock, self.on_step, self.waits = clock, on_step, []

    async def __call__(self, s):
        self.waits.append(s)
        self.clock.t += s
        if self.on_step:
            self.on_step(len(self.waits))
        await asyncio.sleep(0)


def recorder():
    out = []
    return out, (lambda ev, **f: out.append((ev, f)))


async def run_watch(streams, clock, on_step, steps=40, **kw):
    sleep = Steps(clock, on_step)
    emitted, emit = recorder()
    logged, log = recorder()
    task = asyncio.create_task(audio.watch_streams(streams, emit, log, clock=clock, sleep=sleep, **kw))
    for _ in range(steps):
        await asyncio.sleep(0)
        if task.done():
            break
    if not task.done():
        task.cancel()
    return task, emitted, logged, sleep


def keep_alive(streams, clock):
    """Callbacks keep running on healthy streams (as PortAudio's would)."""
    for st in streams:
        if st.stream is not None and st.stream.active:
            st.last_cb = clock.t


async def test_healthy_streams_are_left_alone(sd):
    clock = Clock()
    c, p = capture(sd, clock), playback(sd, clock)
    task, emitted, logged, _ = await run_watch([c, p], clock, lambda n: keep_alive([c, p], clock), steps=20)
    assert emitted == [] and sd.inits == 0 and len(sd.streams) == 2
    assert [f["state"] for ev, f in logged] == ["open", "open"]


async def test_a_stream_portaudio_ended_is_reopened_and_the_others_with_it(sd):
    clock = Clock()
    c, p = capture(sd, clock), playback(sd, clock)
    first_in, first_out = c.stream, p.stream

    def step(n):
        if n == 2:
            first_in.die()
        keep_alive([c, p], clock)
    task, emitted, logged, sleep = await run_watch([c, p], clock, step)
    assert emitted[0] == ("error", {"fatal": False, "text": "BlackHole 16ch stopped; reopening"})
    assert emitted[1][1]["fatal"] is False and emitted[1][1]["text"].startswith("BlackHole 16ch reopened after")
    assert sd.inits == 1  # the device list was re-read once
    assert c.stream is not first_in and c.stream.active and p.stream is not first_out and p.stream.active
    assert first_in.closed and first_out.closed
    states = [(f["state"], f.get("reason")) for ev, f in logged if ev == "device"]
    assert ("lost", "stream stopped") in states and states[-1][0] == "reopened"


async def test_an_exception_in_the_callback_is_recorded_not_raised_into_the_engine(sd):
    clock = Clock()
    c = capture(sd, clock)
    c.loop = None  # the next callback fails
    with pytest.raises(CallbackAbort):
        c._cb(np.ones((1600, 1), dtype=np.int16), 1600, None, None)  # one full chunk
    assert c.problem(clock.t).startswith("AttributeError")


async def test_a_stalled_stream_is_reopened(sd):
    clock = Clock()
    c, p = capture(sd, clock), playback(sd, clock)

    def step(n):
        keep_alive([p], clock)  # the capture callback never runs again
        if n > 8:
            keep_alive([c], clock)
    task, emitted, logged, _ = await run_watch([c, p], clock, step)
    lost = [f for ev, f in logged if f["state"] == "lost"]
    assert lost[0]["name"] == "BlackHole 16ch" and lost[0]["reason"].startswith("no audio callback for")
    assert any(f["state"] == "reopened" for ev, f in logged)


async def test_status_flags_are_counted_not_fatal(sd):
    clock = Clock()
    p = playback(sd, clock)
    out = np.zeros((480, 1), dtype=np.int16)
    p._cb(out, 480, None, "output underflow")
    p._cb(out, 480, None, None)
    assert p.xruns == 1 and p.problem(clock.t) is None


async def test_our_own_close_is_not_a_device_loss(sd):
    clock = Clock()
    c = capture(sd, clock)
    st = c.stream
    c.close()
    assert st.closed and not c.finished


async def test_device_back_after_a_while_under_a_new_index(sd):
    clock = Clock()
    index = {"now": 7}
    c = capture(sd, clock, resolve=lambda: index["now"])
    p = playback(sd, clock)

    def step(n):
        if n == 2:
            c.stream.die()
            sd.gone.add(7)  # CoreAudio removed it
        if n == 6:
            index["now"] = 9  # it came back, listed under another index
        keep_alive([c, p], clock)
    task, emitted, logged, sleep = await run_watch([c, p], clock, step, steps=60)
    failed = [f for ev, f in logged if f["state"] == "reopen_failed"]
    assert len(failed) >= 2 and "device unavailable" in failed[0]["reason"]
    assert sleep.waits[2:2 + len(failed)] == list(audio.REOPEN_BACKOFF_S[:len(failed)])  # backoff 0.5, 1, 2, ...
    assert c.stream.device == 9 and c.stream.active and p.stream.active
    assert [t for ev, t in emitted][-1]["text"].startswith("BlackHole 16ch reopened after")


async def test_device_gone_for_good_is_fatal_after_the_give_up_time(sd):
    clock = Clock()
    c, p = capture(sd, clock), playback(sd, clock)

    def step(n):
        if n == 1:
            c.stream.die()
            sd.gone.add(7)
        keep_alive([p], clock)
    task, emitted, logged, sleep = await run_watch([c, p], clock, step, steps=200)
    assert task.done()
    with pytest.raises(audio.DeviceLost, match="BlackHole 16ch stopped and could not be reopened"):
        task.result()
    gone = [f for ev, f in logged if f["state"] == "gone"]
    assert gone and gone[0]["after_s"] >= audio.REOPEN_GIVE_UP_S
    assert sum(sleep.waits[1:]) < audio.REOPEN_GIVE_UP_S + 10  # gave up close to 60 s, not later
    assert emitted == [("error", {"fatal": False, "text": "BlackHole 16ch stopped; reopening"})]
    assert c.stream is None and p.stream is None  # everything closed on the way out


async def test_playback_drops_audio_while_reopening_and_starts_clean(sd):
    clock = Clock()
    p = playback(sd, clock)
    p.feed(np.full(2400, 500, dtype="<i2").tobytes())
    assert p.ring.queued() > 0
    p.close()
    p.feed(np.full(2400, 500, dtype="<i2").tobytes())
    p.reopen()
    assert p.ring.queued() == 0  # nothing stale queued behind the live call


# --- the engine stays up ---------------------------------------------------------

async def test_amain_reopens_a_lost_device_without_touching_the_sessions(monkeypatch, sd, tmp_path):
    monkeypatch.setattr(events, "audio_ticker", lambda dirs, emit, interval=1.0: _fast_ticker(dirs, emit))
    monkeypatch.setattr(audio, "WATCH_S", 0.01)
    monkeypatch.setattr(audio, "REOPEN_BACKOFF_S", (0.01,))
    monkeypatch.setattr(cli, "resolve_device", lambda args, name, kind: ({"BlackHole 16ch": 7}.get(name, 4), name))
    sessions = [FakeSession([], block_after=True)]
    connect, handles = make_connect(sessions)
    args = cli.parse_args(["--json", "--only", "in", "--model", "m-translate", "--save-dir", str(tmp_path)])
    dirs = {"IN": (("dev", 7, "BlackHole 16ch"), (4, "AirPods Pro"))}
    cmds: asyncio.Queue = asyncio.Queue()

    async def commands():
        while (l := await cmds.get()) is not None:
            yield l

    rec = Rec()
    task = asyncio.create_task(cli.amain(args, dirs, connect, emit=rec, commands=commands()))
    await wait_for(lambda: len(sd.streams) == 2 and rec.of("audio"))
    cap = next(st for st in sd.streams if st.kind == "input")
    cap.die()
    await wait_for(lambda: len(rec.of("error")) == 2, timeout=3)
    assert rec.of("error")[0] == {"fatal": False, "text": "BlackHole 16ch stopped; reopening"}
    assert "reopened" in rec.of("error")[1]["text"]
    assert len(handles) == 1  # the Gemini session was never reconnected
    cmds.put_nowait('{"cmd":"quit"}')
    await asyncio.wait_for(task, 3)
    md = rec.of("saved")[0]["md"]
    log = [json.loads(l) for l in open(md[:-3] + ".events.jsonl")]
    states = [e["state"] for e in log if e["ev"] == "device"]
    assert states[:2] == ["open", "open"] and "lost" in states and "reopened" in states
    assert log[-1]["ev"] == "exit" and log[-1]["reason"] == "quit"


async def test_amain_exits_fatally_when_the_device_stays_gone(monkeypatch, sd, tmp_path):
    monkeypatch.setattr(events, "audio_ticker", lambda dirs, emit, interval=1.0: _fast_ticker(dirs, emit))
    monkeypatch.setattr(audio, "WATCH_S", 0.01)
    monkeypatch.setattr(audio, "REOPEN_BACKOFF_S", (0.01,))
    monkeypatch.setattr(audio, "REOPEN_GIVE_UP_S", 0.2)
    monkeypatch.setattr(cli, "resolve_device", lambda args, name, kind: ({"BlackHole 16ch": 7}.get(name, 4), name))
    connect, _ = make_connect([FakeSession([], block_after=True)])
    args = cli.parse_args(["--json", "--only", "in", "--model", "m-translate", "--save-dir", str(tmp_path)])
    dirs = {"IN": (("dev", 7, "BlackHole 16ch"), (4, "AirPods Pro"))}

    async def commands():
        await asyncio.Event().wait()
        yield ""

    rec = Rec()
    task = asyncio.create_task(cli.amain(args, dirs, connect, emit=rec, commands=commands()))
    await wait_for(lambda: len(sd.streams) == 2)
    sd.gone.add(7)
    next(st for st in sd.streams if st.kind == "input").die()
    with pytest.raises(audio.DeviceLost):
        await asyncio.wait_for(task, 3)
    md = rec.of("saved")[0]["md"]
    log = [json.loads(l) for l in open(md[:-3] + ".events.jsonl")]
    assert log[-1] == {"t": log[-1]["t"], "ev": "exit", "reason": "device lost"}
    assert any(e.get("state") == "gone" for e in log)
