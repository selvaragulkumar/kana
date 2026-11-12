import asyncio
import contextlib
import io
import json
from types import SimpleNamespace as NS

import pytest

from kana import __main__ as cli
from kana import events
from kana.ptt import PTT
from kana.session import Direction
from tests.test_session import FakeSession, content, make_connect, resp, wait_for


class Rec:
    """Emitter stand-in that keeps (ev, fields) and also proves each encodes."""

    def __init__(self):
        self.buf = io.StringIO()
        self.e = events.Emitter(self.buf, clock=lambda: 1700000000.25)
        self.items = []

    def __call__(self, ev, **fields):
        self.items.append((ev, fields))
        self.e.emit(ev, **fields)

    def lines(self):
        return [json.loads(l) for l in self.buf.getvalue().splitlines()]

    def of(self, ev):
        return [f for e, f in self.items if e == ev]


@pytest.mark.parametrize("ev,fields", [
    ("ready", {"in": {"src": "BlackHole 16ch", "sink": "AirPods"},
               "out": {"src": "MacBook Pro Microphone", "sink": "BlackHole 2ch"},
               "model": "m", "in_lang": "en", "out_lang": "ja"}),
    ("talk", {"on": False}),
    ("transcript", {"dir": "in", "kind": "src", "text": "こんにちは。", "final": True}),
    ("session", {"dir": "out", "state": "reconnecting", "detail": "go_away"}),
    ("audio", {"dir": "in", "sent_s": 12.3, "recv_s": 9.8}),
    ("error", {"fatal": True, "text": "boom"}),
    ("usage", {"dir": "out", "model": "gemini-3.8-live", "in_audio_tokens": 283, "out_audio_tokens": 103, "usd": 0.003154,
               "in_text_tokens": 390}),
    ("bye", {}),
])
def test_emitter_encodes_one_json_line(ev, fields):
    buf = io.StringIO()
    events.Emitter(buf, clock=lambda: 1700000000.25).emit(ev, **fields)
    out = buf.getvalue()
    assert out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"t": 1700000000.25, "ev": ev, **fields}
    if ev == "transcript":
        assert "こんにちは" in out  # UTF-8, not \u escapes


def test_audio_seconds():
    assert events.audio_seconds(NS(chunks_sent=123, audio_bytes=48000 * 9.8)) == (12.3, 9.8)


async def aiter(lines):
    for l in lines:
        await asyncio.sleep(0)
        yield l


async def test_command_loop_talk_and_quit():
    ptt, rec = PTT(muted=True, out=lambda *_: None), Rec()
    seen = []

    async def lines():
        for l in ['{"cmd":"talk","on":true}\n', "\n", '{"cmd":"talk","on":false}\n',
                  "garbage\n", '{"cmd":"talk","on":true}\n']:
            yield l
            seen.append(ptt.muted)
        yield '{"cmd":"quit"}\n'
        raise AssertionError("read past quit")

    await events.command_loop(lines(), ptt, rec)
    assert seen == [False, False, True, True, False]
    assert rec.of("talk") == [{"on": True}, {"on": False}, {"on": True}]
    assert rec.of("error") == [{"fatal": False, "text": "unknown command: garbage"}]


async def test_command_loop_returns_on_eof():
    ptt = PTT(muted=False, out=lambda *_: None)
    await asyncio.wait_for(events.command_loop(aiter(['{"cmd":"talk","on":false}']), ptt, Rec()), 1)
    assert ptt.muted


async def test_stdin_lines_reads_a_blocking_stream():
    got = [l async for l in events.stdin_lines(io.StringIO('{"cmd":"quit"}\nx\n'))]
    assert got == ['{"cmd":"quit"}\n', "x\n"]


def test_devices_json():
    devs = [{"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
            {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2}]
    assert cli.devices_json(devs) == {
        "inputs": [{"index": 0, "name": "MacBook Pro Microphone"}, {"index": 2, "name": "BlackHole 2ch"}],
        "outputs": [{"index": 1, "name": "MacBook Pro Speakers"}, {"index": 2, "name": "BlackHole 2ch"}]}


def test_list_devices_json_cli_prints_valid_json(capsys):
    assert cli.main(["--list-devices", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    obj = json.loads(out[0])
    assert set(obj) == {"inputs", "outputs"}
    for d in obj["inputs"] + obj["outputs"]:
        assert isinstance(d["index"], int) and isinstance(d["name"], str)


def test_missing_key_emits_fatal_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", cli.Path("/nonexistent"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert cli.main(["--json", "--only", "in"]) == 2
    line = json.loads(capsys.readouterr().out.strip())
    assert line["ev"] == "error" and line["fatal"] is True and "GEMINI_API_KEY" in line["text"]


async def test_direction_emits_transcripts_and_session_states():
    s1 = FakeSession([[
        resp(server_content=content(inp="こんにちは。")),
        resp(server_content=content(outp="Hello,")),
        resp(server_content=content(outp=" nice weather.", audio=b"\0\0" * 24000, turn_complete=True)),
    ], [resp(go_away=NS(time_left="1s"))]])
    s2 = FakeSession([], block_after=True)
    connect, _ = make_connect([s1, s2])
    rec, plain = Rec(), []
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect,
                  out=plain.append, emit=rec, backoff=(0.01,))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.connects == 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert plain == []  # nothing plain in JSON mode
    assert rec.of("transcript") == [
        {"dir": "in", "kind": "src", "text": "こんにちは。", "row": 1, "row_text": "こんにちは。", "final": True},
        {"dir": "in", "kind": "dst", "text": "Hello, nice weather.", "row": 1, "row_text": "Hello, nice weather.",
         "final": True}]
    assert rec.of("session") == [
        {"dir": "in", "state": "connected", "detail": ""},
        {"dir": "in", "state": "reconnecting", "detail": "go_away"},
        {"dir": "in", "state": "connected", "detail": ""},
        {"dir": "in", "state": "closed", "detail": ""}]
    assert events.audio_seconds(d)[1] == 1.0


async def test_direction_error_session_detail():
    @contextlib.asynccontextmanager
    async def connect(model, config):
        raise ConnectionError("boom")
        yield

    rec = Rec()
    d = Direction("OUT", "en", "ja", "m-translate", asyncio.Queue(), connect=connect, emit=rec, backoff=(0.01,))
    task = asyncio.create_task(d.run())
    await wait_for(lambda: rec.of("session"))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    s = rec.of("session")[0]
    assert s["state"] == "reconnecting" and s["detail"].startswith("error: ") and "boom" in s["detail"]


class FakeStream:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    async def pump(self, q):
        await asyncio.Event().wait()


async def test_amain_json_mode_ready_talk_audio_and_quit(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.audio, "Playback", FakeStream)
    monkeypatch.setattr(cli.audio, "Capture", FakeStream)
    monkeypatch.setattr(events, "audio_ticker",
                        lambda dirs, emit, interval=1.0: _fast_ticker(dirs, emit))
    sessions = [FakeSession([], block_after=True), FakeSession([], block_after=True)]
    connect, _ = make_connect(sessions)
    args = cli.parse_args(["--json", "--model", "m-translate", "--save-dir", str(tmp_path)])
    dirs = {"IN": (("dev", 5, "BlackHole 16ch"), (1, "AirPods")),
            "OUT": (("dev", 0, "MacBook Pro Microphone"), (4, "BlackHole 2ch"))}
    cmds: asyncio.Queue = asyncio.Queue()

    async def commands():
        while (l := await cmds.get()) is not None:
            yield l

    rec = Rec()
    task = asyncio.create_task(cli.amain(args, dirs, connect, emit=rec, commands=commands()))
    await wait_for(lambda: rec.of("audio"))
    assert rec.items[0] == ("ready", {
        "in": {"src": "BlackHole 16ch", "sink": "AirPods"},
        "out": {"src": "MacBook Pro Microphone", "sink": "BlackHole 2ch"},
        "model": "m-translate", "register": "default", "in_model": "m-translate",
        "out_model": "m-translate", "in_lang": "en", "out_lang": "ja"})
    assert rec.items[1][0] == "saved"
    md, srt = rec.items[1][1]["md"], rec.items[1][1]["srt"]
    assert md.startswith(str(tmp_path)) and md.endswith(".md") and srt.endswith(".srt")
    assert rec.items[2] == ("talk", {"on": False})
    cmds.put_nowait('{"cmd":"talk","on":true}')
    await wait_for(lambda: len(rec.of("talk")) == 2)
    cmds.put_nowait('{"cmd":"quit"}')
    await asyncio.wait_for(task, 2)
    assert rec.of("talk")[-1] == {"on": True}
    assert {f["dir"] for f in rec.of("audio")} == {"in", "out"}
    assert set(rec.of("audio")[0]) == {"dir", "sent_s", "recv_s", "gated_s", "latency_ms", "usd"}
    assert {(f["dir"], f["state"]) for f in rec.of("session")} >= {("in", "closed"), ("out", "closed")}
    assert all(json.loads(l) for l in rec.buf.getvalue().splitlines())


async def _fast_ticker(dirs, emit):
    while True:
        await asyncio.sleep(0.01)
        for label, d in dirs.items():
            emit("audio", **events.audio_fields(label, d))


def um(p_audio=0, r_audio=0, p_text=0):
    from google.genai import types
    pd = [NS(modality=types.MediaModality.AUDIO, token_count=p_audio)] if p_audio else []
    if p_text:
        pd.append(NS(modality=types.MediaModality.TEXT, token_count=p_text))
    rd = [NS(modality=types.MediaModality.AUDIO, token_count=r_audio)] if r_audio else []
    return NS(prompt_token_count=p_audio + p_text, response_token_count=r_audio,
              prompt_tokens_details=pd, response_tokens_details=rd)


async def test_usage_deltas_accumulate_and_emit():
    s = FakeSession([[
        resp(usage_metadata=um(50, 50)),          # Live Translate: a delta every 1-2 s
        resp(usage_metadata=um(25, 25)),
        resp(usage_metadata=um(283, 103, 390)),   # general model: one per turn, with text
        resp(usage_metadata=um()),                # nothing new: no event
        resp(usage_metadata=NS(prompt_token_count=10, response_token_count=0,
                               prompt_tokens_details=None, response_tokens_details=None)),
    ]], block_after=True)
    connect, _ = make_connect([s])
    rec = Rec()
    d = Direction("IN", "ja", "en", "gemini-3.5-live-translate-preview", asyncio.Queue(), connect=connect, emit=rec)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: len(rec.of("usage")) == 4)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    u = rec.of("usage")
    assert [(e["in_audio_tokens"], e["out_audio_tokens"]) for e in u] == [(50, 50), (75, 75), (358, 178), (368, 178)]
    assert u[2]["in_text_tokens"] == 390 and u[0]["model"] == "gemini-3.5-live-translate-preview"
    assert rec.of("error") == []  # a known model: no rate warning
    assert u[-1]["usd"] == round(368 * 3.5e-6 + 178 * 21e-6, 6) == d.usd()
    assert events.audio_fields("IN", d)["usd"] == d.usd()


async def _usage_run(model):
    s = FakeSession([[resp(usage_metadata=um(1000, 1000)), resp(usage_metadata=um(1000, 1000))]], block_after=True)
    connect, _ = make_connect([s])
    rec = Rec()
    d = Direction("OUT", "en", "ja", model, asyncio.Queue(), connect=connect, emit=rec)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: len(rec.of("usage")) == 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    return d, rec


async def test_usage_priced_by_model_actually_used():
    from kana.session import AUDIO_RATES_PER_M
    assert AUDIO_RATES_PER_M == {"gemini-3.5-live-translate-preview": (3.50, 21.00), "gemini-3.8-live": (3.00, 12.00)}
    d, rec = await _usage_run("gemini-3.8-live")
    assert rec.of("usage")[-1] == {"dir": "out", "model": "gemini-3.8-live", "in_audio_tokens": 2000,
                                    "out_audio_tokens": 2000, "usd": 0.03, "in_text_tokens": 0}
    d, rec = await _usage_run("gemini-3.5-live-translate-preview")
    assert rec.of("usage")[-1]["usd"] == 0.049 and rec.of("error") == []


async def test_unknown_model_assumes_live_translate_rates_and_warns_once():
    d, rec = await _usage_run("some-future-live-model")
    assert rec.of("usage")[-1]["usd"] == 0.049
    errs = rec.of("error")
    assert len(errs) == 1 and errs[0]["fatal"] is False and "some-future-live-model" in errs[0]["text"]
