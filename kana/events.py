"""JSON line protocol for the menu-bar app (--json).

Engine -> app: one JSON object per line on stdout, each with "t" (unix
seconds) and "ev". App -> engine: JSON lines on stdin, {"cmd":"talk","on":bool}
and {"cmd":"quit"}; EOF on stdin also means quit. In --passthrough only quit
applies."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time


class Emitter:
    def __init__(self, stream=None, clock=time.time):
        self.stream = stream if stream is not None else sys.stdout
        self.clock = clock

    def __call__(self, ev: str, **fields) -> None:
        self.emit(ev, **fields)

    def emit(self, ev: str, **fields) -> None:
        obj = {"t": round(self.clock(), 3), "ev": ev, **fields}
        self.stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.stream.flush()


def audio_seconds(direction) -> tuple[float, float]:
    """Cumulative (sent, received) seconds: 16 kHz int16 out, 24 kHz int16 back."""
    return round(direction.bytes_sent / 32000, 1), round(direction.audio_bytes / 48000, 1)


def audio_fields(label: str, d) -> dict:
    sent, recv = audio_seconds(d)
    f = {"dir": label.lower(), "sent_s": sent, "recv_s": recv,
         "gated_s": d.vad.gated_s, "latency_ms": d.latency_ms(), "usd": d.usd()}
    if getattr(d, "usd_is_estimate", False):  # priced from audio sent, not server-reported usage
        f["est"] = True
    return f


async def audio_ticker(directions: dict, emit, interval: float = 1.0) -> None:
    while True:
        await asyncio.sleep(interval)
        for label, d in directions.items():
            emit("audio", **audio_fields(label, d))


async def stdin_lines(stream=None):
    """Async iterator over lines of a (blocking) stream, read on a daemon
    thread so a pending read never holds up shutdown. Works for pipes, TTYs
    and files alike."""
    stream = stream if stream is not None else sys.stdin
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def reader():
        try:
            for line in stream:
                loop.call_soon_threadsafe(q.put_nowait, line)
        except Exception:
            pass
        finally:
            try:
                loop.call_soon_threadsafe(q.put_nowait, None)
            except RuntimeError:  # loop already closed
                pass

    threading.Thread(target=reader, name="stdin-commands", daemon=True).start()
    while (line := await q.get()) is not None:
        yield line


async def command_loop(lines, ptt, emit) -> None:
    """Apply app commands to the PTT until quit or EOF; returns on either."""
    async for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
            name = cmd.get("cmd") if isinstance(cmd, dict) else None
        except ValueError:
            name = None
        if name == "quit":
            return
        if name == "talk" and isinstance(cmd.get("on"), bool):
            ptt.muted = not cmd["on"]
            emit("talk", on=not ptt.muted)
            continue
        emit("error", fatal=False, text=f"unknown command: {raw[:200]}")


async def passthrough_command_loop(lines, emit) -> None:
    """Pass-through takes only quit (or EOF); talk does not apply, because the
    microphone goes to the meeting directly and is muted in the meeting app."""
    async for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
            name = cmd.get("cmd") if isinstance(cmd, dict) else None
        except ValueError:
            name = None
        if name == "quit":
            return
        if name == "talk":
            emit("error", fatal=False, text="talk does not apply in pass-through: mute in the meeting app")
            continue
        emit("error", fatal=False, text=f"unknown command: {raw[:200]}")
