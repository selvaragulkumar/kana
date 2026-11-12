"""Saved call transcripts: one Markdown table and one SRT per run, appended
utterance by utterance and flushed on every write so a crash loses nothing."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

ARROW = {"in": "↓", "out": "↑"}


def default_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "kana"


def srt_time(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def md_cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


class TranscriptWriter:
    """Times passed to add() are on the `mono` clock; `start_wall`/`start_mono`
    map them to wall-clock times (Markdown) and to offsets (SRT)."""

    def __init__(self, base: Path, start_wall: dt.datetime | None = None, start_mono: float | None = None,
                 title: str = ""):
        self.start_wall = start_wall or dt.datetime.now()
        self.start_mono = time.monotonic() if start_mono is None else start_mono
        folder = Path(base) / "transcripts"
        folder.mkdir(parents=True, exist_ok=True)
        stem = self.start_wall.strftime("%Y-%m-%d-%H%M")
        n = 1
        while (folder / f"{stem}.md").exists() or (folder / f"{stem}.srt").exists():
            n += 1
            stem = f"{self.start_wall.strftime('%Y-%m-%d-%H%M')}-{n}"
        self.md, self.srt = folder / f"{stem}.md", folder / f"{stem}.srt"
        self.index = 0
        head = f"# kana transcript {self.start_wall.strftime('%Y-%m-%d %H:%M')}\n\n"
        if title:
            head += f"{title}\n\n"
        head += "| Time | Dir | Source | Translation |\n|---|---|---|---|\n"
        self._write(self.md, head)
        self._write(self.srt, "")

    @staticmethod
    def _write(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()

    def add(self, direction: str, source: str, translation: str, first: float, last: float) -> None:
        if not (source or translation):
            return
        wall = self.start_wall + dt.timedelta(seconds=first - self.start_mono)
        self._write(self.md, f"| {wall.strftime('%H:%M:%S')} | {ARROW.get(direction, direction)} | "
                             f"{md_cell(source)} | {md_cell(translation)} |\n")
        self.index += 1
        a = first - self.start_mono
        b = max(last - self.start_mono, a + 0.5)
        text = " → ".join(t for t in (" ".join(source.split()), " ".join(translation.split())) if t)
        self._write(self.srt, f"{self.index}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n")
