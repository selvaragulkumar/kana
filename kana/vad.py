"""Energy voice-activity detection on fixed-size int16 chunks (chunk_ms, 100 ms by default).

speech  = rms > max(floor * ratio, threshold), where floor is the rolling noise
          floor: the lowest chunk level of the previous 5 s (0 until 5 s of history
          exist), so steady background noise is learnt and stops counting as
          speech after at most 5 s, and speech at the start of a stream opens.
onset   = first speech chunk after silence; the pre-roll (the last 300 ms of
          gated chunks) is released with it so word starts are not clipped.
end     = DEFAULT_HANGOVER_MS (2 s) of non-speech after the last speech chunk;
          the hangover chunks are still sent, then audio_stream_end once.

With gate=False the detector still classifies (for latency onsets) but every
chunk is sent and no stream end is signalled."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

import numpy as np

# Measured with the Live Translate model (docs/LATENCY.md, 2026-11-13): with
# less than ~2 s of trailing audio the end of the last sentence is held back
# and spoken at the start of the next utterance (en->ja at 1-1.5 s; ja->en at
# 1 s, e.g. "...いいですね" -> "nice," + "isn't it?" later). The silence must
# be real time: sending it at once (flush_ms) does not finish the sentence sooner.
DEFAULT_HANGOVER_MS = 2000


def audible(pcm: bytes, floor: int = 64) -> bool:
    """True when int16 audio has any sample above `floor` (the model streams
    digital silence between translations)."""
    x = np.frombuffer(pcm, dtype="<i2")
    return bool(len(x)) and int(np.abs(x.astype(np.int32)).max()) > floor


def rms(chunk: bytes) -> float:
    x = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


@dataclass
class Decision:
    send: list[bytes] = field(default_factory=list)
    onset: bool = False  # this decision starts an utterance
    end: bool = False    # hangover expired: signal audio_stream_end once


class VAD:
    def __init__(self, gate: bool = True, threshold: float = 200.0, ratio: float = 3.0,
                 hangover_ms: int = DEFAULT_HANGOVER_MS, preroll_ms: int = 300, floor_window_ms: int = 5000,
                 chunk_ms: int = 100, flush_ms: int = 0):
        # All windows are durations, converted to chunk counts, so the detector
        # behaves the same at any chunk size. The threshold is an RMS level and
        # does not depend on chunk length.
        self.gate, self.threshold, self.ratio, self.chunk_ms = gate, threshold, ratio, chunk_ms
        self.levels: collections.deque[float] = collections.deque(maxlen=max(1, round(floor_window_ms / chunk_ms)))
        self.hangover = max(1, round(hangover_ms / chunk_ms))
        self.preroll: collections.deque[bytes] = collections.deque(maxlen=max(0, round(preroll_ms / chunk_ms)))
        # flush: digital silence sent at once (faster than real time) when the
        # hangover expires, before the stream end. A benchmark knob; it did not
        # finish sentences sooner (docs/LATENCY.md), so kana leaves it at 0.
        self.flush_chunks = max(0, round(flush_ms / chunk_ms))
        self.speaking = False
        self._quiet = 0
        self.gated_chunks = 0

    @property
    def gated_s(self) -> float:
        return round(self.gated_chunks * self.chunk_ms / 1000, 1)

    @property
    def floor(self) -> float:
        # Until 5 s of history exist the missing past counts as silence, so a
        # stream that starts in speech is not learnt as its own noise floor.
        return min(self.levels) if len(self.levels) == self.levels.maxlen else 0.0

    def is_speech(self, level: float) -> bool:
        return level > max(self.floor * self.ratio, self.threshold)

    def reset(self) -> None:
        """Back to silence without signalling (used when the user mutes)."""
        self.speaking, self._quiet = False, 0
        self.preroll.clear()

    def push(self, chunk: bytes) -> Decision:
        level = rms(chunk)
        speech = self.is_speech(level)  # judged against the floor of the chunks before it
        self.levels.append(level)
        d = Decision()
        if speech:
            self._quiet = 0
            if not self.speaking:
                self.speaking, d.onset = True, True
                if self.gate:
                    d.send.extend(self.preroll)
                    self.gated_chunks -= len(self.preroll)
                self.preroll.clear()
            d.send.append(chunk)
        elif self.speaking:
            self._quiet += 1
            d.send.append(chunk)  # hangover chunks are still sent
            if self._quiet >= self.hangover:
                self.speaking, self._quiet = False, 0
                d.end = self.gate
                if self.gate and self.flush_chunks:
                    d.send.extend([bytes(len(chunk))] * self.flush_chunks)
        elif self.gate:
            if self.preroll.maxlen:
                self.preroll.append(chunk)
            self.gated_chunks += 1
        else:
            d.send.append(chunk)
        return d
