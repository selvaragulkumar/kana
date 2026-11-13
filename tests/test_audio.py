import asyncio
import wave

import numpy as np
import pytest

from kana import audio
from kana.ptt import PTT

DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    {"name": "BlackHole 16ch", "max_input_channels": 16, "max_output_channels": 16},
]


def test_find_device_substring_case_insensitive():
    assert audio.find_device("macbook", "input", DEVICES) == 0
    assert audio.find_device("MACBOOK", "output", DEVICES) == 1
    assert audio.find_device("blackhole 16", "input", DEVICES) == 3
    assert audio.find_device("blackhole 2ch", "output", DEVICES) == 2


def test_find_device_none_means_default():
    assert audio.find_device(None, "input", DEVICES) is None


def test_find_device_missing_names_the_device():
    with pytest.raises(audio.DeviceError, match='"BlackHole 64ch"'):
        audio.find_device("BlackHole 64ch", "output", DEVICES)
    with pytest.raises(audio.DeviceError):  # right name, wrong direction
        audio.find_device("Speakers", "input", DEVICES)


def test_resample_48k_to_16k():
    x = (np.sin(np.arange(4800) / 10) * 10000).astype(np.int16)
    y = audio.resample(x, 48000, 16000)
    assert y.dtype == np.int16 and y.ndim == 1 and len(y) == 1600


def test_resample_24k_to_48k():
    x = np.arange(2400, dtype=np.int16)
    y = audio.resample(x, 24000, 48000)
    assert y.dtype == np.int16 and y.shape == (4800,)
    assert y[0] == 0 and y[-1] == 2399


def test_resample_same_rate_is_identity():
    x = np.arange(10, dtype=np.int16)
    assert np.array_equal(audio.resample(x, 16000, 16000), x)


def test_ring_pads_silence_on_underrun():
    r = audio.Ring()
    r.push(np.array([1, 2, 3], dtype=np.int16))
    r.push(np.array([4], dtype=np.int16))
    assert list(r.read(2)) == [1, 2]
    assert list(r.read(4)) == [3, 4, 0, 0]
    assert list(r.read(3)) == [0, 0, 0]


def test_put_latest_drops_oldest():
    q = asyncio.Queue(maxsize=2)
    for i in range(3):
        audio.put_latest(q, i)
    assert [q.get_nowait(), q.get_nowait()] == [1, 2]


def test_read_wav_16k_resamples_stereo_48k(tmp_path):
    p = tmp_path / "s.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.zeros(48000 * 2, dtype="<i2").tobytes())
    assert len(audio.read_wav_16k(str(p))) == 16000 * 2


def test_ptt_toggle_and_quit():
    lines = []
    p = PTT(muted=True, out=lines.append)
    assert p.muted
    assert p.handle_key(" ") == "toggle" and not p.muted
    assert p.handle_key(" ") == "toggle" and p.muted
    assert p.handle_key("x") is None and p.muted
    assert p.handle_key("q") == "quit"
    assert len(lines) == 2 and "MUTED" in lines[-1]


def test_ring_counts_queued_samples():
    r = audio.Ring()
    r.push(np.ones(5, dtype=np.int16))
    r.push(np.ones(3, dtype=np.int16))
    assert r.queued() == 8
    r.read(6)
    assert r.queued() == 2
    r.read(10)  # underrun pads, never goes negative
    assert r.queued() == 0


def test_catch_up_drops_silence_only_while_behind():
    sil = np.zeros(2400, dtype=np.int16)
    speech = np.concatenate([np.zeros(1000, dtype=np.int16), np.full(1400, 3000, dtype=np.int16)])
    assert audio.catch_up(sil, queued=0, max_queued=0) is sil  # not behind: keep the pause
    assert len(audio.catch_up(sil, queued=10, max_queued=0)) == 0  # behind: drop streamed silence
    out = audio.catch_up(speech, queued=10, max_queued=0)
    assert len(out) == 1400 and out[0] == 3000  # behind: start at the first audible sample
    assert len(audio.catch_up(speech, queued=10, max_queued=100)) == 2400  # within the allowance


def test_playback_feed_skips_streamed_silence_while_behind():
    p = audio.Playback.__new__(audio.Playback)
    p.ring, p.rate, p.catch_up_ms = audio.Ring(), audio.OUT_RATE, 0
    p.feed(np.zeros(2400, dtype="<i2").tobytes())  # nothing queued: silence is kept
    p.feed(np.zeros(2400, dtype="<i2").tobytes())  # behind: dropped
    p.feed(np.full(2400, 500, dtype="<i2").tobytes())
    assert p.ring.queued() == 4800


def test_rechunker_collects_small_blocks_into_100ms_chunks():
    r = audio.Rechunker()
    x = np.arange(4000, dtype=np.int16)
    out = []
    for k in range(0, 4000, 160):  # 10 ms blocks
        out += r.push(x[k:k + 160])
    assert [len(c) for c in out] == [audio.CHUNK_BYTES, audio.CHUNK_BYTES]
    assert np.array_equal(np.frombuffer(b"".join(out), dtype="<i2"), x[:3200])
    assert len(r.buf) == 800  # the rest waits for the next blocks


def test_rechunker_passes_a_full_chunk_through():
    r = audio.Rechunker()
    x = np.full(1600, 7, dtype=np.int16)
    assert r.push(x) == [x.astype("<i2").tobytes()]
    assert len(r.buf) == 0


def test_capture_passes_latency_and_block_to_portaudio(monkeypatch):
    import sounddevice as sd
    opened = []

    class FakeInputStream:
        def __init__(self, **kw):
            opened.append(kw)
    monkeypatch.setattr(sd, "InputStream", FakeInputStream)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kw: None)
    loop = asyncio.new_event_loop()
    try:
        audio.Capture(3, asyncio.Queue(), loop)
        audio.Capture(3, asyncio.Queue(), loop, latency="low", block_ms=10)
    finally:
        loop.close()
    assert opened[0]["blocksize"] == 1600 and "latency" not in opened[0]  # unchanged default
    assert opened[1]["blocksize"] == 160 and opened[1]["latency"] == "low"


def test_capture_callback_delivers_100ms_chunks_from_small_blocks(monkeypatch):
    import sounddevice as sd
    monkeypatch.setattr(sd, "InputStream", lambda **kw: None)
    monkeypatch.setattr(sd, "check_input_settings", lambda **kw: None)
    loop = asyncio.new_event_loop()
    try:
        q: asyncio.Queue = asyncio.Queue()
        c = audio.Capture(3, q, loop, latency="low", block_ms=10)
        for _ in range(25):
            c._cb(np.ones((160, 1), dtype=np.int16), 160, None, None)
        loop.run_until_complete(asyncio.sleep(0))
        assert q.qsize() == 2 and len(q.get_nowait()) == audio.CHUNK_BYTES
    finally:
        loop.close()


def test_capture_options_low_latency_for_blackhole_only():
    assert audio.capture_options("BlackHole 16ch") == {"latency": "low", "block_ms": 10}
    assert audio.capture_options("BlackHole 2ch", "low") == {"latency": "low", "block_ms": 10}
    assert audio.capture_options("BlackHole 16ch", "default") == {}
    assert audio.capture_options("MacBook Pro Microphone") == {}  # not measured: unchanged
    assert audio.capture_options(None) == {}


def test_capture_latency_flag_defaults_to_low():
    from kana import __main__ as cli
    assert cli.parse_args([]).capture_latency == "low"
    assert cli.parse_args(["--capture-latency", "default"]).capture_latency == "default"
