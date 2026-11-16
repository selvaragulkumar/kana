"""Raw per-call events log: `<stem>.events.jsonl` next to the saved transcript.

One JSON object per line: "t" (unix seconds, 3 decimals), "dir" ("in"/"out",
absent for engine-wide events) and "ev", plus a few small fields. It records
every server message kind a direction sees (transcription chunks, turn signals,
audio, usage, go_away, resumption), the session lifecycle, utterances,
keepalives and every `transcript` op the pairer emits, so that a call's pairing
can be replayed offline (kana/replay.py) and diffed. Audio content, resumption
handles and API keys are never written. Flushed per line, like the transcript
files, so a crash loses nothing."""
from __future__ import annotations

import json
import time
from pathlib import Path


class EventLog:
    def __init__(self, path: Path | str, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self._f = open(self.path, "a", encoding="utf-8")

    def __call__(self, dir: str | None, ev: str, **fields) -> None:
        if self._f is None:
            return
        obj = {"t": round(self.clock(), 3)}
        if dir:
            obj["dir"] = dir
        obj["ev"] = ev
        obj.update({k: v for k, v in fields.items() if v is not None})
        self._f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._f.flush()

    def for_dir(self, dir: str):
        """A callable (ev, **fields) bound to one direction."""
        return lambda ev, **fields: self(dir, ev, **fields)

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None
