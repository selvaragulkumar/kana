"""Audio devices, resampling, WAV sources and the two stream kinds.

All PCM handed around as bytes is mono int16 little-endian.
Capture is 16 kHz in 100 ms chunks (3200 bytes); playback is 24 kHz.
sounddevice callbacks run on PortAudio threads and hand data to asyncio
with loop.call_soon_threadsafe; they never block.
"""
from __future__ import annotations

import asyncio
import collections
import wave

import numpy as np

IN_RATE = 16000
OUT_RATE = 24000
CHUNK_MS = 100
CHUNK_BYTES = IN_RATE * CHUNK_MS // 1000 * 2  # 3200


class DeviceError(RuntimeError):
    pass


def find_device(name: str | None, kind: str, devices=None) -> int | None:
    """Index of the first device whose name contains `name` (case-insensitive)
    and has channels of `kind` ("input"/"output"). None name -> None (= default)."""
    if name is None:
        return None
    if devices is None:
        import sounddevice as sd
        devices = sd.query_devices()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(devices):
        if name.lower() in d["name"].lower() and d[key] > 0:
            return i
    raise DeviceError(f'No {kind} device matching "{name}" (run with --list-devices to see what is available)')


def device_name(index: int | None, kind: str) -> str:
    import sounddevice as sd
    return sd.query_devices(index, kind)["name"]


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear resampling of a 1-D int16 array."""
    if src == dst or len(x) == 0:
        return x.astype(np.int16, copy=False)
    n = int(round(len(x) * dst / src))
    t = np.linspace(0, len(x) - 1, n) if n > 1 else np.zeros(n)
    return np.interp(t, np.arange(len(x)), x.astype(np.float32)).round().astype(np.int16)


def put_latest(q: asyncio.Queue, item) -> None:
    """put_nowait that drops the oldest item when the queue is full."""
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(item)


def read_wav_16k(path: str) -> bytes:
    """Read a 16-bit PCM WAV and return 16 kHz mono int16 bytes."""
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: only 16-bit PCM WAV is supported")
        ch, rate = w.getnchannels(), w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return resample(x, rate, IN_RATE).astype("<i2").tobytes()


async def feed_file(pcm: bytes, q: asyncio.Queue) -> None:
    """Feed WAV audio in real-time 100 ms chunks, then silence forever so the
    model sees the end of speech."""
    silence = bytes(CHUNK_BYTES)
    loop = asyncio.get_running_loop()
    start = loop.time()
    i = 0
    while True:
        chunk = pcm[i * CHUNK_BYTES:(i + 1) * CHUNK_BYTES] or silence
        put_latest(q, chunk.ljust(CHUNK_BYTES, b"\0"))
        i += 1
        await asyncio.sleep(max(0.0, start + i * CHUNK_MS / 1000 - loop.time()))


def _pick_rate(check, device, wanted: int, kind: str) -> int:
    import sounddevice as sd
    try:
        check(device=device, samplerate=wanted, channels=1, dtype="int16")
        return wanted
    except Exception:
        return int(sd.query_devices(device, kind)["default_samplerate"])


class Capture:
    """Input stream -> asyncio queue of 3200-byte 16 kHz chunks."""

    def __init__(self, device: int | None, q: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        import sounddevice as sd
        self.q, self.loop = q, loop
        self.rate = _pick_rate(sd.check_input_settings, device, IN_RATE, "input")
        self.stream = sd.InputStream(device=device, samplerate=self.rate, channels=1, dtype="int16",
                                     blocksize=self.rate * CHUNK_MS // 1000, callback=self._cb)

    def _cb(self, indata, frames, time_info, status):
        x = resample(indata[:, 0].copy(), self.rate, IN_RATE)
        self.loop.call_soon_threadsafe(put_latest, self.q, x.astype("<i2").tobytes())

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()


class Ring:
    """Lock-free FIFO of int16 arrays; read() pads with silence on underrun.
    One producer (asyncio) appends, one consumer (audio thread) reads."""

    def __init__(self):
        self.chunks: collections.deque[np.ndarray] = collections.deque()
        self.cur = np.zeros(0, dtype=np.int16)

    def push(self, x: np.ndarray) -> None:
        self.chunks.append(x)

    def read(self, n: int) -> np.ndarray:
        out = np.zeros(n, dtype=np.int16)
        filled = 0
        while filled < n:
            if len(self.cur) == 0:
                try:
                    self.cur = self.chunks.popleft()
                except IndexError:
                    break
            k = min(n - filled, len(self.cur))
            out[filled:filled + k] = self.cur[:k]
            self.cur = self.cur[k:]
            filled += k
        return out


class Playback:
    """Output stream fed from 24 kHz PCM bytes; silence on underrun."""

    def __init__(self, device: int | None):
        import sounddevice as sd
        self.ring = Ring()
        self.rate = _pick_rate(sd.check_output_settings, device, OUT_RATE, "output")
        self.stream = sd.OutputStream(device=device, samplerate=self.rate, channels=1, dtype="int16",
                                      callback=self._cb)

    def feed(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm, dtype="<i2")
        self.ring.push(resample(x, OUT_RATE, self.rate))

    def _cb(self, outdata, frames, time_info, status):
        outdata[:, 0] = self.ring.read(frames)

    async def pump(self, q: asyncio.Queue) -> None:
        while True:
            self.feed(await q.get())

    def __enter__(self):
        self.stream.start()
        return self

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()
