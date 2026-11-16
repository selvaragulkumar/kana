"""Offline replay of a saved call: reads `<stem>.events.jsonl` (kana/eventlog.py)
and re-feeds the raw transcription chunks, turn signals, model audio and
utterance boundaries of one direction, at their logged times, through the same
`Direction` text path and pairer the live engine uses. Out come the rows and
the `transcript` ops, so a pairing change can be tested against real arrival
timing and diffed against what the app showed during the call.

    python -m kana.replay path/to/2026-11-16-0931.events.jsonl [--dir in] [--logged]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace as NS

from .session import Direction


def load(path: Path | str) -> list[dict]:
    """The events of a .events.jsonl, in file order. A torn last line (a crash
    mid-write) is skipped."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


class _Clock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class App:
    """Applies `transcript` ops the way the app does (EngineProcess.swift): by row id."""

    def __init__(self):
        self.rows: dict[int, list[str]] = {}

    def apply(self, op: dict) -> None:
        if "merge_into" in op:
            self.rows.pop(op["row"], None)
            self.rows.setdefault(op["merge_into"], ["", ""])[0] = op["row_text"]
            return
        row = self.rows.setdefault(op["row"], ["", ""])
        row[0 if op["kind"] == "src" else 1] = op["row_text"]

    def table(self) -> list[tuple[str, str]]:
        return [tuple(self.rows[k]) for k in sorted(self.rows)]


@dataclass
class Result:
    rows: list[tuple[str, str]] = field(default_factory=list)  # saved rows (source, translation), in order
    ops: list[dict] = field(default_factory=list)              # transcript ops, as the app would get them
    app: App = field(default_factory=App)                      # the app's view after applying the ops


def _content(**kw) -> NS:
    base = dict(input_transcription=None, output_transcription=None, model_turn=None, turn_complete=False,
                generation_complete=False, interrupted=False)
    base.update(kw)
    return NS(**base)


def _audio(audible: bool) -> NS:
    data = (b"\0\x10" if audible else b"\0\0") * 4
    return NS(parts=[NS(inline_data=NS(data=data))])


def replay(events: list[dict], dir: str = "in", pairer_factory=None) -> Result:
    """Replays one direction of a call. `pairer_factory(on_row=...)` replaces the
    default pairer (to compare pairing versions on the same call)."""
    res = Result()
    clock = _Clock(events[0]["t"] if events else 0.0)

    def emit(ev, **fields):
        if ev == "transcript":
            op = {k: v for k, v in fields.items() if k not in ("dir", "final")}
            res.ops.append(op)
            res.app.apply(op)

    def on_row(_dir, r):
        res.rows.append((r.src_text, r.dst_text))

    d = Direction(dir.upper(), "src", "dst", "replay", asyncio.Queue(), connect=None, emit=emit,
                  clock=clock, on_row=on_row)
    if pairer_factory is not None:
        d.pairer = pairer_factory(on_row=lambda r: on_row(dir, r))
    for e in events:
        if e.get("dir") != dir:
            continue
        clock.t = e["t"]
        d._seal()
        ev = e["ev"]
        if ev == "input_transcription" and e.get("text"):
            d._server_content(_content(input_transcription=NS(text=e["text"], finished=e.get("fin"))))
        elif ev == "output_transcription" and e.get("text"):
            d._server_content(_content(output_transcription=NS(text=e["text"], finished=e.get("fin"))))
        elif ev == "audio":
            d._server_content(_content(model_turn=_audio(bool(e.get("audible")))))
        elif ev in ("turn_complete", "generation_complete", "interrupted"):
            d._server_content(_content(**{ev: True}))
        elif ev == "utterance_open":
            if e.get("onset"):
                d._onset()
            elif d.utt is None:
                d._current()
        elif ev == "utterance_close" and e.get("quiet"):
            d._flush()
            d.close_utterance(quiet=True)
        elif ev == "closed":
            d._flush()
        elif ev == "stopped":
            break
    d._flush()  # the end of the run (or of the file, after a crash) seals everything
    d.close_utterance()
    d._seal(force=True)
    return res


def logged_ops(events: list[dict], dir: str = "in") -> list[dict]:
    """The transcript ops the engine actually emitted during the call."""
    return [{k: v for k, v in e.items() if k not in ("t", "dir", "ev")}
            for e in events if e.get("dir") == dir and e["ev"] == "transcript"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m kana.replay", description=__doc__.split("\n\n")[0])
    p.add_argument("path")
    p.add_argument("--dir", default="in", choices=["in", "out"])
    p.add_argument("--logged", action="store_true", help="show the rows the app showed during the call instead")
    a = p.parse_args(argv)
    events = load(a.path)
    if a.logged:
        app = App()
        for op in logged_ops(events, a.dir):
            app.apply(op)
        rows = app.table()
    else:
        rows = replay(events, a.dir).rows
    for src, dst in rows:
        sys.stdout.write(f"{src}\t{dst}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
