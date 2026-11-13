"""OpenAI gpt-realtime-translate provider, against a fake websocket server on localhost."""
import asyncio
import base64
import json

import numpy as np
import pytest
import websockets

from kana import __main__ as cli
from kana import events
from kana.openai_session import OPENAI_MODEL, OpenAIDirection, make_connect
from kana.vad import VAD
from tests.test_events import FakeStream, Rec
from tests.test_session import wait_for

KEY = "sk-test-not-a-real-key"


class FakeServer:
    """Speaks the translation websocket protocol. `script(conn_no, ws, server)` runs
    after the handshake for each connection; every client event is recorded."""

    def __init__(self, script=None):
        self.script = script
        self.conns = []  # per connection: {"path", "auth", "events": [...]}
        self.url = None

    async def handler(self, ws):
        rec = {"path": ws.request.path, "auth": ws.request.headers.get("Authorization"), "events": []}
        self.conns.append(rec)
        n = len(self.conns)
        await ws.send(json.dumps({"type": "session.created", "session": {"type": "translation"}}))
        reader = asyncio.create_task(self._read(ws, rec))
        await wait_for(lambda: any(e["type"] == "session.update" for e in rec["events"]))
        await ws.send(json.dumps({"type": "session.updated", "session": {"type": "translation"}}))
        try:
            if self.script:
                await self.script(n, ws, self)
            await reader
        finally:
            reader.cancel()

    async def _read(self, ws, rec):
        try:
            async for raw in ws:
                ev = json.loads(raw)
                rec["events"].append(ev)
                if ev["type"] == "session.close":
                    await ws.send(json.dumps({"type": "session.closed"}))
        except websockets.ConnectionClosed:
            pass

    def appended(self, n=None):
        conns = self.conns if n is None else [self.conns[n - 1]]
        return [e for c in conns for e in c["events"] if e["type"] == "session.input_audio_buffer.append"]


@pytest.fixture
async def server():
    srv = FakeServer()
    async with websockets.serve(srv.handler, "127.0.0.1", 0) as s:
        port = s.sockets[0].getsockname()[1]
        srv.url = f"ws://127.0.0.1:{port}/v1/realtime/translations"
        yield srv


def pcm_b64(samples: int, value: int = 3000) -> str:
    return base64.b64encode(np.full(samples, value, dtype="<i2").tobytes()).decode()


def direction(srv, rec=None, out_q=None, **kw):
    in_q: asyncio.Queue = asyncio.Queue()
    d = OpenAIDirection("IN", "ja", "en", OPENAI_MODEL, in_q, out_q if out_q is not None else asyncio.Queue(),
                        connect=make_connect(KEY, url=srv.url), emit=rec, out=lambda *_: None,
                        vad=VAD(gate=False), backoff=(0.05,), **kw)
    return d, in_q


async def test_connect_configures_language_and_sends_resampled_audio(server):
    rec = Rec()
    d, in_q = direction(server, rec)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: d.session is not None)
    c = server.conns[0]
    assert c["path"] == f"/v1/realtime/translations?model={OPENAI_MODEL}"
    assert c["auth"] == f"Bearer {KEY}"
    upd = next(e for e in c["events"] if e["type"] == "session.update")
    assert upd["session"]["audio"]["output"]["language"] == "en"
    assert upd["session"]["audio"]["input"]["transcription"]["model"]
    for _ in range(12):  # 1.2 s of 16 kHz audio
        in_q.put_nowait(np.full(1600, 1000, dtype="<i2").tobytes())
    await wait_for(lambda: len(server.appended()) == 12)
    pcm = base64.b64decode(server.appended()[0]["audio"])
    assert len(pcm) == 2400 * 2  # 100 ms at 24 kHz
    assert d.chunks_sent == 12 and d.bytes_sent == 12 * 3200
    assert d.usd() == round(1.2 / 60 * 0.034, 6)
    usage = rec.of("usage")
    # one usage event per whole second sent
    assert usage == [{"dir": "in", "model": OPENAI_MODEL, "sent_s": 1.0, "usd": round(1 / 60 * 0.034, 6),
                      "est": True}]
    assert events.audio_fields("IN", d)["est"] is True
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await wait_for(lambda: any(e["type"] == "session.close" for e in c["events"]))
    assert rec.of("session")[0] == {"dir": "in", "state": "connected", "detail": ""}
    assert rec.of("session")[-1]["state"] == "closed"
    assert KEY not in rec.buf.getvalue()


async def test_audio_and_transcript_deltas_reach_queue_and_events(server):
    async def script(n, ws, srv):
        await ws.send(json.dumps({"type": "session.input_transcript.delta", "delta": "こんにちは。"}))
        await ws.send(json.dumps({"type": "session.output_transcript.delta", "delta": "Hello"}))
        await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": pcm_b64(4800)}))
        await ws.send(json.dumps({"type": "session.output_transcript.delta", "delta": ", everyone."}))
        await ws.send(json.dumps({"type": "session.output_audio.delta", "delta": pcm_b64(4800, 0)}))
    server.script = script
    rec, out_q = Rec(), asyncio.Queue()
    d, _ = direction(server, rec, out_q)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: out_q.qsize() == 2 and d.transcript("out") == "Hello, everyone.")
    assert out_q.get_nowait() == np.full(4800, 3000, dtype="<i2").tobytes()
    assert d.audio_bytes == 2 * 9600
    assert d.transcript("in") == "こんにちは。"
    tr = rec.of("transcript")
    assert {(t["kind"], t["text"]) for t in tr} == {("src", "こんにちは。"), ("dst", "Hello, everyone.")}
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_reconnects_after_drop_and_server_error(server):
    async def script(n, ws, srv):
        if n == 1:
            await ws.close(code=1011, reason="boom")  # abnormal close
        elif n == 2:
            await ws.send(json.dumps({"type": "error", "error": {"type": "server_error", "code": "x",
                                                                   "message": "transient"}}))
        else:
            await ws.send(json.dumps({"type": "session.output_transcript.delta", "delta": "Back."}))
    server.script = script
    rec = Rec()
    d, in_q = direction(server, rec)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: d.transcript("out") == "Back.", timeout=5)
    assert len(server.conns) == 3 and d.connects == 3
    states = [(s["state"], s["detail"]) for s in rec.of("session")]
    assert states[0] == ("connected", "")
    assert any(st == "reconnecting" and "x: transient" in det for st, det in states)
    assert [s for s, _ in states].count("connected") == 3
    in_q.put_nowait(bytes(3200))  # audio after the reconnect goes to the new socket only
    await wait_for(lambda: len(server.appended(3)) == 1)
    assert server.appended(1) == server.appended(2) == []
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_muted_stream_end_is_not_sent(server):
    d, in_q = direction(server, is_muted=lambda: True)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: d.session is not None)
    for _ in range(5):
        in_q.put_nowait(np.full(1600, 5000, dtype="<i2").tobytes())
    await asyncio.sleep(0.2)
    assert server.appended() == [] and d.usd() == 0
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_provider_resolution():
    a = cli.parse_args([])
    assert (a.provider, a.model, a.provider_error) == ("gemini", "gemini-3.5-live-translate-preview", None)
    a = cli.parse_args(["--provider", "openai"])
    assert (a.provider, a.model) == ("openai", OPENAI_MODEL)
    assert cli.direction_models(a) == {"IN": (OPENAI_MODEL, None), "OUT": (OPENAI_MODEL, None)}
    a = cli.parse_args(["--model", OPENAI_MODEL])
    assert (a.provider, a.model, a.provider_error) == ("openai", OPENAI_MODEL, None)
    assert cli.parse_args(["--provider", "gemini", "--model", OPENAI_MODEL]).provider_error
    assert cli.parse_args(["--provider", "openai", "--model", "gemini-3.8-live"]).provider_error
    assert "business" in cli.parse_args(["--provider", "openai", "--register", "business"]).provider_error


def test_missing_openai_key_is_one_fatal_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "ROOT", cli.Path("/nonexistent"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-not-used")
    assert cli.main(["--json", "--only", "in", "--provider", "openai"]) == 2
    lines = [json.loads(l) for l in capsys.readouterr().out.strip().splitlines()]
    assert len(lines) == 1
    assert lines[0]["ev"] == "error" and lines[0]["fatal"] is True and "OPENAI_API_KEY" in lines[0]["text"]


def test_business_register_on_openai_is_fatal(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert cli.main(["--json", "--provider", "openai", "--register", "business"]) == 2
    line = json.loads(capsys.readouterr().out.strip())
    assert line["fatal"] is True and "--register business" in line["text"]


async def test_amain_openai_ready_reports_model(monkeypatch, tmp_path, server):
    monkeypatch.setattr(cli.audio, "Playback", FakeStream)
    monkeypatch.setattr(cli.audio, "Capture", FakeStream)
    args = cli.parse_args(["--json", "--provider", "openai", "--only", "in", "--no-save"])
    dirs = {"IN": (("dev", 5, "BlackHole 16ch"), (1, "AirPods"))}
    rec = Rec()

    async def commands():
        await wait_for(lambda: any(s["state"] == "connected" for s in rec.of("session")))
        yield '{"cmd":"quit"}'

    await asyncio.wait_for(cli.amain(args, dirs, make_connect(KEY, url=server.url), emit=rec,
                                     commands=commands()), 5)
    ready = rec.of("ready")[0]
    assert ready["model"] == ready["in_model"] == OPENAI_MODEL and ready["out_model"] is None
