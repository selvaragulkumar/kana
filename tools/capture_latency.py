"""Capture latency on BlackHole, measured silently through its loopback.

BlackHole is a virtual loopback: what is written to its output comes back on
its input. A click is written to the BlackHole 16ch output (the meeting's
speakers) and the engine's own `audio.Capture` reads it back from the
BlackHole 16ch input, the way kana's inbound direction hears a meeting.

    .venv/bin/python tools/capture_latency.py                  # 30 clicks per capture latency
    .venv/bin/python tools/capture_latency.py --playback-s 30  # also BlackHole 2ch underruns

Per click (all on time.monotonic):
- write: the output callback that puts the click in its buffer (output stream
  at latency "low", the same for every capture setting, so differences are the
  capture side's);
- arrival: the 100 ms chunk holding the click reaches the asyncio queue;
- delay = arrival - write. It includes waiting for the 100 ms block to fill;
  `overhead` subtracts that wait (the samples after the click in its chunk).

Settings are interleaved (A/B/A/B) so drift does not bias one of them. The
capture callbacks' status flags (input overflow) are counted.

`--playback-s` also plays digital silence (nothing audible) through the
engine's `audio.Playback` to BlackHole 2ch (the meeting's microphone) at each
output latency and counts output underflows.

Only the devices named exactly "BlackHole 16ch" and "BlackHole 2ch" are
opened; never a microphone, speakers or the default device.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kana import audio  # noqa: E402

LOOP_DEV = "BlackHole 16ch"
MEET_MIC = "BlackHole 2ch"
CLICK_LEVEL = 20000
DETECT_LEVEL = 4000


def exact_device(name: str, kind: str) -> int:
    import sounddevice as sd
    i = audio.find_device(name, kind)
    if sd.query_devices(i)["name"] != name:  # never fall through to another device
        raise SystemExit(f"device {i} is {sd.query_devices(i)['name']!r}, not {name!r}")
    return i


class FlagCapture(audio.Capture):
    """The engine's Capture, counting PortAudio status flags."""
    def __init__(self, *a, **kw):
        self.flags = 0
        self.overflows = 0
        super().__init__(*a, **kw)

    def _cb(self, indata, frames, time_info, status):
        if status:
            self.flags += 1
            self.overflows += int(bool(status.input_overflow))
        super()._cb(indata, frames, time_info, status)


class Clicker:
    """Output stream on the BlackHole 16ch output that writes one 1 ms click
    when asked and records when."""
    def __init__(self, device: int, rate: int = 48000):
        import sounddevice as sd
        self.rate = rate
        self.want = False
        self.t_write: float | None = None
        self.flags = 0
        self.stream = sd.OutputStream(device=device, samplerate=rate, channels=1, dtype="int16",
                                      latency="low", callback=self._cb)

    def _cb(self, outdata, frames, time_info, status):
        if status:
            self.flags += 1
        outdata.fill(0)
        if self.want:
            self.want = False
            n = min(frames, self.rate // 1000)
            outdata[:n, 0] = CLICK_LEVEL
            self.t_write = time.monotonic()

    def click(self) -> None:
        self.t_write = None
        self.want = True


async def measure(cap_latency, clicks: int, loop_in: int, loop_out: int, block_ms: int = audio.CHUNK_MS) -> dict:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    clicker = Clicker(loop_out)
    delays, overheads, misses = [], [], 0
    with clicker.stream, FlagCapture(loop_in, q, loop, latency=cap_latency, block_ms=block_ms) as cap:
        reported = cap.stream.latency
        await asyncio.sleep(1.0)  # let both streams settle
        while not q.empty():
            q.get_nowait()
        for _ in range(clicks):
            await asyncio.sleep(random.uniform(0.35, 0.65))  # random phase within the 100 ms block
            while not q.empty():
                q.get_nowait()
            clicker.click()
            got = False
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                try:
                    chunk = await asyncio.wait_for(q.get(), 0.5)
                except asyncio.TimeoutError:
                    continue
                t_arr = time.monotonic()
                x = np.frombuffer(chunk, dtype="<i2")
                loud = np.nonzero(np.abs(x.astype(np.int32)) > DETECT_LEVEL)[0]
                if len(loud) and clicker.t_write is not None:
                    d = t_arr - clicker.t_write
                    delays.append(d * 1000)
                    overheads.append((d - (len(x) - loud[0]) / audio.IN_RATE) * 1000)
                    got = True
                    break
            misses += 0 if got else 1
        flags, overflows = cap.flags, cap.overflows
    return {"latency": cap_latency, "block_ms": block_ms, "reported_ms": round(reported * 1000, 1), "rate": cap.rate,
            "delays": delays, "overheads": overheads, "misses": misses, "in_flags": flags,
            "in_overflows": overflows, "out_flags": clicker.flags}


def stats(v):
    if not v:
        return "n=0"
    s = sorted(v)
    p90 = s[min(len(s) - 1, int(np.ceil(0.9 * len(s))) - 1)]
    return f"median {statistics.median(s):.1f} p90 {p90:.1f} min {s[0]:.1f} max {s[-1]:.1f} n={len(s)}"


async def playback_check(device: int, latency, seconds: float) -> dict:
    """Digital silence through the engine's Playback in the model's bursty
    pattern (250 ms chunks); count output underflows."""
    class FlagPlayback(audio.Playback):
        def __init__(self, *a, **kw):
            self.flags = 0
            self.underflows = 0
            super().__init__(*a, **kw)

        def _cb(self, outdata, frames, time_info, status):
            if status:
                self.flags += 1
                self.underflows += int(bool(status.output_underflow))
            super()._cb(outdata, frames, time_info, status)

    p = FlagPlayback(device, catch_up_ms=None, latency=latency)
    chunk = bytes(audio.OUT_RATE // 4 * 2)  # 250 ms of silence
    with p:
        reported = p.stream.latency
        t0 = time.monotonic()
        k = 0
        while time.monotonic() - t0 < seconds:
            for _ in range(random.choice([1, 2, 3])):  # bursts, like the model
                p.feed(chunk)
                k += 1
            await asyncio.sleep(max(0.0, t0 + k * 0.25 - time.monotonic()))
    return {"latency": latency, "reported_ms": round(reported * 1000, 1), "rate": p.rate,
            "flags": p.flags, "underflows": p.underflows}


async def main_async(args) -> None:
    loop_in, loop_out = exact_device(LOOP_DEV, "input"), exact_device(LOOP_DEV, "output")
    def setting(s):  # "low" or "low/10": capture latency / PortAudio block ms
        lat, _, blk = s.partition("/")
        lat = None if lat == "default" else lat if lat in ("low", "high") else float(lat)
        return lat, int(blk or audio.CHUNK_MS)
    settings = [setting(s) for s in args.settings.split(",")]
    labels = {s: f"latency={s[0] or 'default'} block={s[1]} ms" for s in settings}
    res = {s: [] for s in settings}
    for r in range(args.rounds):  # interleaved A/B/A/B
        for s in settings:
            m = await measure(s[0], args.clicks // args.rounds, loop_in, loop_out, s[1])
            res[s].append(m)
            print(f"round {r} {labels[s]}: reported {m['reported_ms']} ms @ {m['rate']} Hz | "
                  f"delay {stats(m['delays'])} | misses {m['misses']} in_flags {m['in_flags']} "
                  f"overflows {m['in_overflows']} out_flags {m['out_flags']}", flush=True)
    print("\n== capture: BlackHole 16ch output -> BlackHole 16ch input, engine Capture (100 ms blocks)")
    for s, ms in res.items():
        d = [x for m in ms for x in m["delays"]]
        o = [x for m in ms for x in m["overheads"]]
        print(f"{labels[s]} (reported {ms[0]['reported_ms']} ms)\n  delay    {stats(d)}\n"
              f"  overhead {stats(o)}\n  misses {sum(m['misses'] for m in ms)}  input flags "
              f"{sum(m['in_flags'] for m in ms)}  overflows {sum(m['in_overflows'] for m in ms)}  "
              f"output flags {sum(m['out_flags'] for m in ms)}")
    if args.playback_s:
        meet_mic = exact_device(MEET_MIC, "output")
        print("\n== playback: digital silence via engine Playback -> BlackHole 2ch")
        for _ in range(args.rounds):
            for s in dict.fromkeys(x[0] for x in settings):
                r = await playback_check(meet_mic, s, args.playback_s)
                print(f"latency={s or 'default'}: reported {r['reported_ms']} ms @ {r['rate']} Hz | "
                      f"{args.playback_s:.0f} s | status flags {r['flags']} underflows {r['underflows']}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--clicks", type=int, default=60, help="per setting, split over --rounds")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--settings", default="default,low,default/10,low/10",
                   help="comma list of capture latency (default, low, high or seconds), optionally /block ms")
    p.add_argument("--playback-s", type=float, default=0.0)
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
