"""Audio devices, resampling, WAV sources and the two stream kinds.

All PCM handed around as bytes is mono int16 little-endian.
Capture is 16 kHz in 100 ms chunks (3200 bytes); playback is 24 kHz.
sounddevice callbacks run on PortAudio threads and hand data to asyncio
with loop.call_soon_threadsafe; they never block.
"""
from __future__ import annotations

import asyncio
import collections
import sys
import wave

import numpy as np

IN_RATE = 16000
OUT_RATE = 24000
CHUNK_MS = 100
CHUNK_BYTES = IN_RATE * CHUNK_MS // 1000 * 2  # 3200


class DeviceError(RuntimeError):
    pass


# MME (the first Windows host API) cuts device names to 31 characters:
# "CABLE-A Output (VB-Audio Cable A)" -> "CABLE-A Output (VB-Audio Cable ".
MME_NAME_MAX = 31


def default_host_api(platform: str | None = None) -> str | None:
    """Host API used when --host-api is "auto". Windows lists every endpoint once per
    host API (MME first, then DirectSound, WASAPI, WDM-KS) and PortAudio's default is
    MME, whose "low" latency is about 90 ms; WASAPI (shared mode) is picked instead.
    Elsewhere there is one host API (Core Audio) or the system's choice: no filter.
    See docs/research/windows.md."""
    platform = sys.platform if platform is None else platform
    return "wasapi" if platform == "win32" else None


def meeting_cables(platform: str | None = None) -> tuple[str, str]:
    """Default (--meet-mic, --meet-spk) names. macOS: BlackHole 2ch and 16ch. Windows:
    VB-Audio's CABLE-A and CABLE-B (docs/research/windows.md); each name matches both
    ends of its cable and the direction picks the end."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return "CABLE-A", "CABLE-B"
    return "BlackHole 2ch", "BlackHole 16ch"


def is_virtual_cable(name: str | None) -> bool:
    """BlackHole, VB-Audio cables (also when MME cut the name) and Virtual Audio Cable."""
    n = (name or "").lower()
    return ("blackhole" in n or "vb-audio" in n or n.startswith(("cable ", "cable-"))
            or "virtual audio cable" in n)


def cable_label(name: str) -> str:
    return "a BlackHole device" if "blackhole" in name.lower() else "a virtual audio cable"


def cable_id(name: str) -> str:
    """One key for both ends of a cable. BlackHole has one name for both ends; VB-Audio
    names the playback end "<id> Input" and the recording end "<id> Output", and MME
    may cut either name, so a VB-Audio cable is keyed by the part before that word:
    "CABLE-A Input (VB-Audio Cable A)" -> "cable-a". Other names are lower-cased."""
    n = name.lower()
    if "blackhole" not in n and is_virtual_cable(n):
        for word in (" input", " output"):
            if word in n:
                return n.split(word)[0]
    return n


def _other_end(query: str) -> str | None:
    """The same VB-Audio query naming the other end: the meeting app's microphone is
    "CABLE-A Output", which the engine writes to as "CABLE-A Input"."""
    q = query.lower()
    if " output" in q:
        return q.replace(" output", " input")
    if " input" in q:
        return q.replace(" input", " output")
    return None


def _name_matches(query: str, name: str) -> bool:
    q, n = query.lower(), name.lower()
    return q in n or (len(n) >= MME_NAME_MAX and q.startswith(n))


def host_api_index(query: str, hostapis) -> int:
    for i, h in enumerate(hostapis):
        if query.lower() in h["name"].lower():
            return i
    names = ", ".join(h["name"] for h in hostapis)
    raise DeviceError(f'No audio host API matching "{query}" (available: {names})')


def find_device(name: str | None, kind: str, devices=None, host_api: str | None = None,
                hostapis=None) -> int | None:
    """Index of the first device whose name contains `name` (case-insensitive)
    and has channels of `kind` ("input"/"output"). None name -> None (= default).

    With `host_api` (a substring of a PortAudio host API name, such as "wasapi") only
    that host API's devices count, and a None name gives that host API's default
    device. A name cut by MME (31 characters) still matches when the query is the
    full name, and a VB-Audio cable named by its other end ("CABLE-A Output" for the
    output side) matches the end of the right kind. Without `host_api` and with a
    name that matches directly, the result is the same as before these rules."""
    if name is None and host_api is None:
        return None
    if devices is None or (host_api is not None and hostapis is None):
        import sounddevice as sd
        devices = sd.query_devices() if devices is None else devices
        hostapis = sd.query_hostapis() if hostapis is None else hostapis
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    allowed = list(range(len(devices)))
    if host_api is not None:
        ha = host_api_index(host_api, hostapis)
        if name is None:
            i = hostapis[ha][f"default_{kind}_device"]
            if i is None or i < 0:
                raise DeviceError(f'{hostapis[ha]["name"]} has no default {kind} device')
            return i
        allowed = [i for i in allowed if devices[i].get("hostapi") == ha]
    for i in allowed:
        if _name_matches(name, devices[i]["name"]) and devices[i][key] > 0:
            return i
    other = _other_end(name)
    if other is not None:
        for i in allowed:
            d = devices[i]
            if is_virtual_cable(d["name"]) and _name_matches(other, d["name"]) and d[key] > 0:
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


class Rechunker:
    """Collects 16 kHz int16 blocks of any size into CHUNK_MS chunks (bytes)."""

    def __init__(self, samples: int = IN_RATE * CHUNK_MS // 1000):
        self.samples = samples
        self.buf = np.zeros(0, dtype=np.int16)

    def push(self, x: np.ndarray) -> list[bytes]:
        if len(self.buf) == 0 and len(x) == self.samples:
            return [x.astype("<i2").tobytes()]  # the block is a chunk: no copy
        self.buf = np.concatenate([self.buf, x.astype(np.int16, copy=False)])
        out = []
        while len(self.buf) >= self.samples:
            out.append(self.buf[:self.samples].astype("<i2").tobytes())
            self.buf = self.buf[self.samples:]
        return out


LOW_LATENCY_BLOCK_MS = 10


def capture_options(device_name: str | None, setting: str = "low") -> dict:
    """Capture keyword arguments for a device. "low" opens BlackHole inputs at
    PortAudio latency "low" with 10 ms blocks: on the BlackHole 16ch loopback
    each 100 ms chunk then reaches the engine 7 ms after its last sample instead
    of 67 ms (docs/LATENCY.md). Other inputs (microphones) were not measured and
    keep the defaults. Windows cables (VB-Audio) get the same; not yet measured
    there (docs/research/windows.md)."""
    if setting == "low" and is_virtual_cable(device_name):
        return {"latency": "low", "block_ms": LOW_LATENCY_BLOCK_MS}
    return {}


class Capture:
    """Input stream -> asyncio queue of 3200-byte 16 kHz chunks.

    `block_ms` is the PortAudio block; smaller blocks are collected into 100 ms
    chunks. `latency` is passed to PortAudio ("low", "high" or seconds); None
    keeps sounddevice's default ("high"). With a 100 ms block PortAudio buffers
    the same either way; only a small block with "low" hands each chunk over
    sooner (docs/LATENCY.md)."""

    def __init__(self, device: int | None, q: asyncio.Queue, loop: asyncio.AbstractEventLoop,
                 latency: str | float | None = None, block_ms: int = CHUNK_MS):
        import sounddevice as sd
        self.q, self.loop = q, loop
        self.rate = _pick_rate(sd.check_input_settings, device, IN_RATE, "input")
        self.chunks = Rechunker()
        kw = {} if latency is None else {"latency": latency}
        self.stream = sd.InputStream(device=device, samplerate=self.rate, channels=1, dtype="int16",
                                     blocksize=self.rate * block_ms // 1000, callback=self._cb, **kw)

    def _cb(self, indata, frames, time_info, status):
        for c in self.chunks.push(resample(indata[:, 0].copy(), self.rate, IN_RATE)):
            self.loop.call_soon_threadsafe(put_latest, self.q, c)

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
        self.pushed = 0  # samples ever pushed (producer only)
        self.played = 0  # samples ever read out of the queue (consumer only)

    def push(self, x: np.ndarray) -> None:
        self.chunks.append(x)
        self.pushed += len(x)

    def queued(self) -> int:
        """Samples waiting to be played (approximate while the consumer reads)."""
        return max(0, self.pushed - self.played)

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
        self.played += filled
        return out


def catch_up(x: np.ndarray, queued: int, max_queued: int, floor: int = 64) -> np.ndarray:
    """What to queue of a model chunk `x` when `queued` samples already wait.
    The model streams digital silence around its speech, often in bursts
    faster than real time; queued back-to-back that silence delays the next
    words. While more than `max_queued` samples wait, an inaudible chunk is
    dropped and an audible one starts at its first audible sample. Within
    speech nothing is dropped, so pauses shorten only while playback is behind."""
    if queued <= max_queued:
        return x
    loud = np.nonzero(np.abs(x.astype(np.int32)) > floor)[0]
    return x[:0] if len(loud) == 0 else x[loud[0]:]


CATCH_UP_MS = 0  # see catch_up(); measured in docs/LATENCY.md


class Playback:
    """Output stream fed from 24 kHz PCM bytes; silence on underrun."""

    def __init__(self, device: int | None, catch_up_ms: int | None = CATCH_UP_MS,
                 latency: str | float | None = None):
        import sounddevice as sd
        self.ring = Ring()
        self.catch_up_ms = catch_up_ms  # None: queue everything back-to-back
        self.rate = _pick_rate(sd.check_output_settings, device, OUT_RATE, "output")
        kw = {} if latency is None else {"latency": latency}
        self.stream = sd.OutputStream(device=device, samplerate=self.rate, channels=1, dtype="int16",
                                      callback=self._cb, **kw)

    def feed(self, pcm: bytes) -> None:
        x = np.frombuffer(pcm, dtype="<i2")
        if self.catch_up_ms is not None:
            x = catch_up(x, self.ring.queued() * OUT_RATE // self.rate, OUT_RATE * self.catch_up_ms // 1000)
        if len(x):
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


PASSTHROUGH_BLOCK_MS = 10
PASSTHROUGH_MAX_MS = 50


def check_passthrough(routes: dict) -> None:
    """Loop safety for --passthrough, before any stream opens. `routes` is
    {"IN"|"OUT": ((src_index, src_name), (sink_index, sink_name))}. The earphones
    (the IN sink) may not be a virtual cable, and no sink may be a cable that a
    loop captures: pass-through never writes to BlackHole 16ch. A physical device
    with input and output of the same name (AirPods) is not a cable, so only cable
    sinks are compared with the sources, by cable_id() because a VB-Audio cable's
    two ends have different names."""
    (_, in_src), (_, in_sink) = routes["IN"]
    if is_virtual_cable(in_sink):
        raise DeviceError(f'Earphones are "{in_sink}", {cable_label(in_sink)}: pass-through would send the '
                          "meeting back into a virtual cable. Pick your real earphones.")
    sources = {cable_id(src) for (_, src), _ in routes.values()}
    for (_, src), (_, sink) in routes.values():
        if is_virtual_cable(sink) and cable_id(sink) in sources:
            raise DeviceError(f'Pass-through would play into "{sink}", which it also captures (feedback loop); '
                              "pick distinct devices")


class Passthrough:
    """Copies one input device to one output device, untranslated, at native quality.

    The input is opened with one channel (channel 0 of the device, e.g. the left
    channel Meet writes to BlackHole 16ch) at its native rate. The output is opened
    at the same rate when it accepts it, otherwise at its own native rate with
    linear resampling, and with up to two channels carrying the same mono signal.
    Blocks are 10 ms at PortAudio latency "low". A deque bridges the two callbacks:
    above `max_ms` queued the oldest block is dropped (clock drift between devices),
    and an underrun plays silence. `sd` is injectable for tests."""

    def __init__(self, src: int | None, dst: int | None, block_ms: int = PASSTHROUGH_BLOCK_MS,
                 max_ms: int = PASSTHROUGH_MAX_MS, sd=None):
        if sd is None:
            import sounddevice as sd
        self.in_rate = int(sd.query_devices(src, "input")["default_samplerate"])
        try:
            sd.check_output_settings(device=dst, samplerate=self.in_rate, channels=1, dtype="int16")
            self.out_rate = self.in_rate
        except Exception:
            self.out_rate = int(sd.query_devices(dst, "output")["default_samplerate"])
        out_ch = max(1, min(2, int(sd.query_devices(dst, "output")["max_output_channels"])))
        self.blocks: collections.deque[np.ndarray] = collections.deque()
        self.cur = np.zeros(0, dtype=np.int16)
        self.max_blocks = max(2, max_ms // block_ms)
        self.dropped = 0  # blocks dropped for drift (diagnostics)
        self.inp = sd.InputStream(device=src, samplerate=self.in_rate, channels=1, dtype="int16",
                                  blocksize=self.in_rate * block_ms // 1000, latency="low", callback=self._in)
        self.out = sd.OutputStream(device=dst, samplerate=self.out_rate, channels=out_ch, dtype="int16",
                                   blocksize=self.out_rate * block_ms // 1000, latency="low", callback=self._out)

    def _in(self, indata, frames, time_info, status):
        self.blocks.append(resample(indata[:, 0].copy(), self.in_rate, self.out_rate))
        while len(self.blocks) > self.max_blocks:
            try:
                self.blocks.popleft()
                self.dropped += 1
            except IndexError:
                break

    def _out(self, outdata, frames, time_info, status):
        out = np.zeros(frames, dtype=np.int16)
        filled = 0
        while filled < frames:
            if len(self.cur) == 0:
                try:
                    self.cur = self.blocks.popleft()
                except IndexError:
                    break
            k = min(frames - filled, len(self.cur))
            out[filled:filled + k] = self.cur[:k]
            self.cur = self.cur[k:]
            filled += k
        outdata[:] = out[:, None]

    def __enter__(self):
        self.out.start()
        try:
            self.inp.start()
        except BaseException:
            self.out.stop()
            self.out.close()
            raise
        return self

    def __exit__(self, *exc):
        for s in (self.inp, self.out):
            s.stop()
            s.close()
