"""Latency per utterance, saved transcripts and the reconnect chaos test."""
import asyncio
import contextlib
import datetime as dt
import re

from kana import events
from kana.session import Direction
from kana.transcripts import TranscriptWriter, srt_time
from kana.vad import VAD
from tests.test_events import Rec
from tests.test_session import content, resp, wait_for
from tests.test_vad import SIL, noise, tone

END = object()  # ends one receive() turn


class LiveFake:
    """A session whose responses are pushed by the test while it runs.
    Push an Exception instance to make receive() raise (dropped socket)."""

    def __init__(self, fail_after_chunks=None):
        self.q: asyncio.Queue = asyncio.Queue()
        self.sent = []
        self.fail_after = fail_after_chunks

    async def send_realtime_input(self, **kw):
        self.sent.append(kw)
        if self.fail_after is not None and sum("audio" in k for k in self.sent) == self.fail_after:
            self.q.put_nowait(ConnectionResetError("socket dropped mid-utterance"))

    async def receive(self):
        while True:
            item = await self.q.get()
            if item is END:
                return
            if isinstance(item, Exception):
                raise item
            yield item


def connector(sessions):
    handles = []

    @contextlib.asynccontextmanager
    async def connect(model, config):
        handles.append(config.session_resumption.handle)
        yield sessions.pop(0)

    return connect, handles


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def audio_chunks(s):
    return [k["audio"].data for k in s.sent if "audio" in k]


async def test_latency_event_per_utterance_and_saved_row(tmp_path):
    clock, rec = Clock(), Rec()
    s = LiveFake()
    connect, _ = connector([s])
    writer = TranscriptWriter(tmp_path, start_wall=dt.datetime(2026, 11, 12, 9, 30, 0), start_mono=100.0)
    in_q, out_q = asyncio.Queue(), asyncio.Queue()
    d = Direction("IN", "ja", "en", "m-translate", in_q, out_q, connect=connect, emit=rec, clock=clock,
                  vad=VAD(hangover_ms=400), on_utterance=lambda dir_, u: writer.add(dir_, " ".join(u.src), " ".join(u.dst),
                                                                      u.first, u.last))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        for _ in range(4):
            in_q.put_nowait(SIL)
        await wait_for(lambda: in_q.empty())
        clock.t = 102.0  # speech onset
        for k in range(5):
            in_q.put_nowait(tone(k=k))
        await wait_for(lambda: len(audio_chunks(s)) == 3 + 5)  # pre-roll + speech
        clock.t = 103.0
        s.q.put_nowait(resp(server_content=content(audio=bytes(9600))))  # streamed silence does not count
        await wait_for(lambda: out_q.qsize() == 1)
        clock.t = 103.84
        s.q.put_nowait(resp(server_content=content(audio=b"\0\x10" * 4800)))
        await wait_for(lambda: out_q.qsize() == 2)
        clock.t = 104.0
        s.q.put_nowait(resp(server_content=content(inp="こんにちは、")))
        s.q.put_nowait(resp(server_content=content(inp="いい天気ですね。")))
        await wait_for(lambda: rec.of("transcript"))
        clock.t = 104.9
        s.q.put_nowait(resp(server_content=content(outp="Hello, nice weather.", audio=b"\0\x10" * 4800)))
        await wait_for(lambda: len(rec.of("transcript")) == 2)
        for _ in range(4):  # hangover then stream end
            in_q.put_nowait(SIL)
        await wait_for(lambda: {"audio_stream_end": True} in s.sent)
        assert not rec.of("latency")  # still within the quiet window
        clock.t = 106.5
        in_q.put_nowait(SIL)
        await wait_for(lambda: rec.of("latency"))
        assert rec.of("latency") == [{"dir": "in", "onset_to_audio_ms": 1840, "src_final_to_dst_final_ms": 900}]
        assert d.latency_ms() == 1840
        f = events.audio_fields("IN", d)
        assert f["latency_ms"] == 1840 and f["gated_s"] == 0.2 and f["sent_s"] == 1.2
        assert out_q.qsize() == 3
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert len(rec.of("latency")) == 1  # closing the run does not emit it again
    md = writer.md.read_text()
    assert "| 09:30:02 | ↓ | こんにちは、いい天気ですね。 | Hello, nice weather. |" in md
    assert writer.srt.read_text() == (
        "1\n00:00:02,000 --> 00:00:04,900\nこんにちは、いい天気ですね。 → Hello, nice weather.\n\n")


async def test_utterance_without_onset_has_null_onset_latency():
    clock, rec = Clock(), Rec()
    s = LiveFake()
    connect, _ = connector([s])
    d = Direction("OUT", "en", "ja", "m-translate", asyncio.Queue(), connect=connect, emit=rec, clock=clock)
    task = asyncio.create_task(d.run())
    await wait_for(lambda: d.session is s)
    s.q.put_nowait(resp(server_content=content(outp="こんにちは。")))
    await wait_for(lambda: rec.of("transcript"))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert rec.of("latency") == [{"dir": "out", "onset_to_audio_ms": None, "src_final_to_dst_final_ms": None}]
    assert d.latency_ms() is None


async def test_quiet_close_flushes_unpunctuated_text_into_the_row(tmp_path):
    clock, rec, rows = Clock(), Rec(), []
    s = LiveFake()
    connect, _ = connector([s])
    in_q = asyncio.Queue()
    d = Direction("IN", "ja", "en", "m-translate", in_q, asyncio.Queue(), connect=connect, emit=rec, clock=clock,
                  vad=VAD(hangover_ms=400), on_utterance=lambda dir_, u: rows.append((u.src, u.dst)))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        in_q.put_nowait(tone())
        s.q.put_nowait(resp(server_content=content(inp="今日はいい天気ですね。", outp="The weather is nice today,")))
        await wait_for(lambda: rec.of("transcript"))
        for _ in range(4):  # hangover
            in_q.put_nowait(SIL)
        await wait_for(lambda: not d.vad.speaking)
        assert rows == []  # still inside the quiet window
        clock.t += 5
        in_q.put_nowait(SIL)
        await wait_for(lambda: rows)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert rows == [(["今日はいい天気ですね。"], ["The weather is nice today,"])]


def test_writer_files_names_and_escaping(tmp_path):
    w1 = TranscriptWriter(tmp_path, start_wall=dt.datetime(2026, 11, 12, 9, 5), start_mono=0.0)
    w2 = TranscriptWriter(tmp_path, start_wall=dt.datetime(2026, 11, 12, 9, 5), start_mono=0.0)
    assert w1.md.name == "2026-11-12-0905.md" and w1.srt.name == "2026-11-12-0905.srt"
    assert w2.md.name == "2026-11-12-0905-2.md"  # never overwrites an earlier run
    w1.add("out", "a | b\nc", "", 3661.25, 3661.25)
    w1.add("in", "", "", 1, 2)  # empty utterances are skipped
    assert "| 10:06:01 | ↑ | a \\| b c |  |" in w1.md.read_text()
    assert w1.srt.read_text() == "1\n01:01:01,250 --> 01:01:01,750\na | b c\n\n"
    assert srt_time(0) == "00:00:00,000"


async def test_reconnect_chaos_mid_utterance(tmp_path):
    """The socket drops after 6 audio chunks, in the middle of speech and of a
    model turn. The direction must resume with the latest handle, never resend a
    chunk, never replay output audio, and keep the transcript files coherent."""
    clock, rec = Clock(), Rec()
    s1, s2 = LiveFake(fail_after_chunks=6), LiveFake()
    connect, handles = connector([s1, s2])
    writer = TranscriptWriter(tmp_path, start_wall=dt.datetime(2026, 11, 12, 10, 0), start_mono=100.0)
    in_q, out_q = asyncio.Queue(), asyncio.Queue()
    d = Direction("IN", "ja", "en", "m-translate", in_q, out_q, connect=connect, emit=rec, clock=clock,
                  backoff=(0.3,), vad=VAD(hangover_ms=400),
                  on_row=lambda dir_, r: writer.add(dir_, r.src_text, r.dst_text, r.first, r.last))
    fed = [tone(amp=3000 + 10 * k) for k in range(40)]  # every chunk distinct
    assert len(set(fed)) == len(fed)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s1)
        s1.q.put_nowait(resp(session_resumption_update=_upd("h1")))
        s1.q.put_nowait(resp(session_resumption_update=_upd("h2")))
        a1 = b"\x00\x11" * 2400
        s1.q.put_nowait(resp(server_content=content(inp="一つ目の文です。", outp="First sentence.", audio=a1)))
        await wait_for(lambda: d.handle == "h2" and out_q.qsize() == 1)
        s1.q.put_nowait(resp(server_content=content(inp="二つ目の")))  # half a sentence when it drops
        await asyncio.sleep(0.02)
        for c in fed[:6]:
            in_q.put_nowait(c)
        await wait_for(lambda: d.session is None)
        # chunks spoken while reconnecting are drained, not queued for a resend
        for c in fed[6:10]:
            in_q.put_nowait(c)
        await wait_for(lambda: in_q.empty())
        assert d.session is None
        await wait_for(lambda: d.session is s2)
        for c in fed[10:30]:
            in_q.put_nowait(c)
        await wait_for(lambda: in_q.empty() and len(audio_chunks(s2)) > 0)
        a2 = b"\x00\x12" * 2400
        s2.q.put_nowait(resp(server_content=content(inp="文です。", outp="Second sentence.", audio=a2)))
        await wait_for(lambda: out_q.qsize() == 2)
        clock.t += 5
        in_q.put_nowait(SIL)
        for _ in range(5):
            in_q.put_nowait(SIL)
        await wait_for(lambda: rec.of("latency"))
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert handles == [None, "h2"]
    sent = [c for c in audio_chunks(s1) + audio_chunks(s2) if c in fed]  # the hangover silence is not distinct
    assert len(sent) == len(set(sent)), "a chunk was sent twice"
    idx = [fed.index(c) for c in sent]
    assert idx == sorted(idx) and audio_chunks(s1) == fed[:6]
    assert idx == list(range(6)) + list(range(10, 30))  # chunks spoken while down are dropped, not resent
    assert [out_q.get_nowait() for _ in range(out_q.qsize())] == [a1, a2]  # no replayed audio
    assert d.audio_bytes == len(a1) + len(a2)

    states = [(e["state"], e["detail"][:6]) for e in rec.of("session")]
    assert states == [("connected", ""), ("reconnecting", "error:"), ("connected", ""), ("closed", "")]
    assert "socket dropped" in rec.of("session")[1]["detail"]

    texts = [(t["kind"], t["text"]) for t in rec.of("transcript")]
    assert [t["row"] for t in rec.of("transcript")] == [1, 1, 2, 2, 2]  # the cut sentence continues its row
    assert texts == [("src", "一つ目の文です。"), ("dst", "First sentence."), ("src", "二つ目の"),
                     ("src", "文です。"), ("dst", "Second sentence.")]
    md_rows = [l for l in writer.md.read_text().splitlines() if l.startswith("| ") and "↓" in l]
    srt_blocks = [b for b in writer.srt.read_text().split("\n\n") if b.strip()]
    assert len(md_rows) == len(srt_blocks) == 2
    assert [int(b.split("\n")[0]) for b in srt_blocks] == list(range(1, len(srt_blocks) + 1))
    # every sentence saved exactly once; the sentence cut by the drop stays one row
    assert [r.split(" | ", 2)[2] for r in md_rows] == ["一つ目の文です。 | First sentence. |",
                                                        "二つ目の文です。 | Second sentence. |"]
    for b in srt_blocks:
        a, z = re.match(r"\d+\n(\S+) --> (\S+)\n", b).groups()
        assert a < z


def _upd(h):
    from types import SimpleNamespace as NS
    return NS(resumable=True, new_handle=h)
