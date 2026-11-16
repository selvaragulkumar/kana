"""The raw per-call events log (kana/eventlog.py) and its offline replay (kana/replay.py)."""
import asyncio
import contextlib
import json
from types import SimpleNamespace as NS

from kana import __main__ as cli
from kana import events
from kana.eventlog import EventLog
from kana.replay import App, load, logged_ops, replay
from kana.session import Direction
from tests.test_events import FakeStream, Rec, _fast_ticker
from tests.test_session import FakeSession, make_connect, resp, wait_for
from tests.test_utterances import END, LiveFake, connector


class Clock:
    def __init__(self, t=1794795000.0):
        self.t = t

    def __call__(self):
        return self.t


def lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def sc(inp=None, outp=None, audio=None, **flags):
    base = dict(input_transcription=NS(text=inp, finished=None) if inp else None,
                output_transcription=NS(text=outp, finished=None) if outp else None,
                model_turn=NS(parts=[NS(inline_data=NS(data=audio))]) if audio else None,
                turn_complete=False, generation_complete=False, interrupted=False)
    base.update(flags)
    return NS(**base)


def test_event_log_lines_are_small_flushed_json(tmp_path):
    clock = Clock(1794795000.12345)
    log = EventLog(tmp_path / "x.events.jsonl", clock=clock)
    log(None, "start", model="m", note=None)
    log.for_dir("in")("input_transcription", text="こんにちは", fin=None)
    assert lines(tmp_path / "x.events.jsonl") == [  # readable before close: flushed per line
        {"t": 1794795000.123, "ev": "start", "model": "m"},
        {"t": 1794795000.123, "dir": "in", "ev": "input_transcription", "text": "こんにちは"}]
    raw = (tmp_path / "x.events.jsonl").read_text()
    assert "こんにちは" in raw and ", " not in raw  # UTF-8, compact separators
    log.close()
    log("in", "late")  # after close: ignored, no error
    assert len(lines(tmp_path / "x.events.jsonl")) == 2


async def test_direction_logs_every_server_message_kind(tmp_path):
    clock = Clock()
    log = EventLog(tmp_path / "e.jsonl", clock=clock)
    usage = NS(prompt_token_count=25, response_token_count=25, total_token_count=50,
               prompt_tokens_details=None, response_tokens_details=None)
    s1 = FakeSession([[
        resp(session_resumption_update=NS(resumable=True, new_handle="secret-handle")),
        resp(server_content=sc(inp="こんにちは")),
        resp(server_content=sc(outp="Hello", audio=b"\0\x10" * 10)),
        resp(server_content=sc(audio=b"\0\0" * 10)),
        resp(server_content=sc(inp="。"), usage_metadata=usage),
        resp(server_content=sc(generation_complete=True)),
        resp(server_content=sc(interrupted=True)),
        resp(server_content=sc(turn_complete=True, turn_complete_reason="TurnCompleteReason.NEED_MORE_INPUT")),
    ], [resp(go_away=NS(time_left="5s"))]])
    s2 = FakeSession([], block_after=True)
    connect, _ = make_connect([s1, s2])
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect, emit=Rec(), clock=clock,
                  backoff=(0.01,), log=log.for_dir("in"))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.connects == 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    log.close()
    got = lines(tmp_path / "e.jsonl")
    assert all(e["dir"] == "in" for e in got)
    evs = [e["ev"] for e in got]
    for kind in ("connected", "session_resumption_update", "input_transcription", "output_transcription",
                 "audio", "usage", "generation_complete", "interrupted", "turn_complete", "transcript",
                 "go_away", "closed", "reconnecting", "utterance_open", "utterance_close", "stopped"):
        assert kind in evs, kind
    assert "secret-handle" not in (tmp_path / "e.jsonl").read_text()  # never the resumption handle
    by = {e["ev"]: e for e in got}
    assert by["session_resumption_update"] == {"t": clock.t, "dir": "in", "ev": "session_resumption_update",
                                               "resumable": True, "handle": True}
    assert [e for e in got if e["ev"] == "audio"] == [
        {"t": clock.t, "dir": "in", "ev": "audio", "bytes": 20, "audible": True},
        {"t": clock.t, "dir": "in", "ev": "audio", "bytes": 20, "audible": False}]
    assert by["usage"]["prompt"] == 25 and by["usage"]["response"] == 25 and by["usage"]["total"] == 50
    assert by["turn_complete"]["reason"] == "NEED_MORE_INPUT"
    assert by["go_away"]["time_left"] == "5s"
    assert [e["reason"] for e in got if e["ev"] == "closed"] == ["go_away", "stopped"] and by["reconnecting"] == {
        "t": clock.t, "dir": "in", "ev": "reconnecting", "reason": "go_away", "delay": 0}
    assert [e["text"] for e in got if e["ev"] == "input_transcription"] == ["こんにちは", "。"]
    tr = [e for e in got if e["ev"] == "transcript"]
    assert tr and all({"kind", "text", "row", "row_text"} <= set(e) for e in tr)
    assert evs.index("connected") < evs.index("input_transcription") < evs.index("stopped")


async def test_keepalive_and_stream_end_are_logged(tmp_path):
    from kana.vad import VAD
    from tests.test_session import StepClock, _feed
    from tests.test_vad import SIL, tone
    s = FakeSession([], block_after=True)
    connect, _ = make_connect([s])
    clock = StepClock()
    log = EventLog(tmp_path / "e.jsonl", clock=clock)
    in_q = asyncio.Queue()
    d = Direction("IN", "ja", "en", "m-translate", in_q, connect=connect, emit=Rec(), clock=clock,
                  vad=VAD(gate=True, hangover_ms=200), keepalive_s=1.0, log=log.for_dir("in"))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        await _feed(d, in_q, clock, [tone(k=k) for k in range(5)] + [SIL] * 20, start=100.0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    evs = [e["ev"] for e in lines(tmp_path / "e.jsonl")]
    assert evs.count("stream_end") == 1 and evs.count("keepalive") == d.keepalives >= 1
    assert evs.index("utterance_open") < evs.index("stream_end") < evs.index("keepalive")


async def test_amain_writes_events_log_beside_the_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.audio, "Playback", FakeStream)
    monkeypatch.setattr(cli.audio, "Capture", FakeStream)
    monkeypatch.setattr(events, "audio_ticker", lambda dirs, emit, interval=1.0: _fast_ticker(dirs, emit))
    connect, _ = make_connect([FakeSession([], block_after=True)])
    args = cli.parse_args(["--json", "--only", "in", "--model", "m-translate", "--save-dir", str(tmp_path)])
    dirs = {"IN": (("dev", 5, "BlackHole 16ch"), (1, "AirPods"))}

    async def commands():
        yield '{"cmd":"quit"}'

    rec = Rec()
    await asyncio.wait_for(cli.amain(args, dirs, connect, emit=rec, commands=commands()), 2)
    md = rec.of("saved")[0]["md"]
    path = md[:-3] + ".events.jsonl"
    got = [json.loads(l) for l in open(path)]
    assert got[0]["ev"] == "start" and got[0]["dirs"] == ["in"] and got[0]["model"] == "m-translate"
    assert got[-1] == {"t": got[-1]["t"], "ev": "exit", "reason": "quit"}
    assert ("in", "stopped") in {(e.get("dir"), e["ev"]) for e in got}


async def test_no_save_writes_no_events_log(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.audio, "Playback", FakeStream)
    monkeypatch.setattr(cli.audio, "Capture", FakeStream)
    monkeypatch.setattr(events, "audio_ticker", lambda dirs, emit, interval=1.0: _fast_ticker(dirs, emit))
    connect, _ = make_connect([FakeSession([], block_after=True)])
    args = cli.parse_args(["--json", "--only", "in", "--no-save", "--save-dir", str(tmp_path)])

    async def commands():
        yield '{"cmd":"quit"}'

    await asyncio.wait_for(cli.amain(args, {"IN": (("dev", 5, "x"), (1, "y"))}, connect, emit=Rec(),
                                     commands=commands()), 2)
    assert not list(tmp_path.rglob("*.events.jsonl"))


async def test_replay_reproduces_the_live_rows_and_ops(tmp_path):
    """A call recorded through a fake session is replayed from its events log alone:
    the same rows are saved and the same transcript ops are emitted."""
    clock = Clock()
    log = EventLog(tmp_path / "e.jsonl", clock=clock)
    s = LiveFake()
    connect, _ = connector([s])
    rec, saved = Rec(), []
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect, emit=rec, clock=clock,
                  on_row=lambda _d, r: saved.append((r.src_text, r.dst_text)), log=log.for_dir("in"))
    script = [  # (seconds after start, server content)
        (1.0, sc(inp="今日は")), (1.3, sc(outp="Today")), (2.0, sc(inp="いい天気ですね。")),
        (2.3, sc(outp=" the weather is nice.", audio=b"\0\x10" * 8)), (3.0, sc(inp="はい。")),
        (3.3, sc(outp="Yes.")), (4.0, sc(inp="それでは")), (4.3, sc(outp="Well then,")),
        (5.0, sc(inp="始めましょう。")), (5.3, sc(outp=" let's begin.")), (6.0, sc(turn_complete=True)),
    ]
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        start = clock.t
        for at, content in script:
            clock.t = start + at
            s.q.put_nowait(resp(server_content=content))
            await wait_for(lambda: s.q.empty())
            for _ in range(5):
                await asyncio.sleep(0)
        s.q.put_nowait(END)
        await asyncio.sleep(0.02)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    log.close()
    live_ops = [{k: v for k, v in f.items() if k not in ("dir", "final")} for f in rec.of("transcript")]
    ev = load(tmp_path / "e.jsonl")
    assert logged_ops(ev, "in") == live_ops
    res = replay(ev, "in")
    assert res.ops == live_ops
    assert res.rows == saved == res.app.table()
    assert [r[0] for r in saved] == ["今日はいい天気ですね。", "はい。", "それでは始めましょう。"]
    assert [r[1] for r in saved] == ["Today the weather is nice.", "Yes.", "Well then, let's begin."]


def test_load_skips_a_torn_last_line(tmp_path):
    p = tmp_path / "c.events.jsonl"
    p.write_text('{"t": 1.0, "dir": "in", "ev": "input_transcription", "text": "はい。"}\n{"t": 2.0, "di')
    assert load(p) == [{"t": 1.0, "dir": "in", "ev": "input_transcription", "text": "はい。"}]


def test_app_applies_merge_ops():
    app = App()
    for op in [{"kind": "src", "text": "a", "row": 1, "row_text": "a"},
               {"kind": "dst", "text": "A", "row": 1, "row_text": "A"},
               {"kind": "src", "text": "b", "row": 2, "row_text": "b"},
               {"kind": "src", "text": "b", "row": 2, "merge_into": 1, "row_text": "a b"}]:
        app.apply(op)
    assert app.table() == [("a b", "A")]
