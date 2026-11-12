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
