"""Pairing v2: source and translation chunks into rows, as they stream.

Measured on Gemini Live Translate (docs/research/transcription-timing.md): the
server streams the input transcription as it hears it, one chunk about every
second, and the output transcription of that chunk follows about 0.3 s later.
The two streams interleave 1:1. What arrived "late and in large chunks" on the
2026-11-16 call was the engine's own sentence buffer: spontaneous Japanese has
no 。 for 20-30 s, so v1 (kana/pairing_v1.py) only saw the source when the
speaker finally finished a sentence, then gave it the next translation. Live
Translate sends no turn_complete, generation_complete or interrupted at all,
so there are no turns to group by.

So v2 takes chunks, not sentences, and pairs them by arrival: the source and
translation of a stretch of speech fill the same row as they stream. A row is
cut where the translation ends a sentence. Rules, per chunk:

Translation chunk (it translates the source chunk that came just before it):
  T1. The last row's translation has not ended a sentence -> append to it
      (it may be a row the source opened a moment ago).
  T2. The last row's translation is done, but the latest source chunk went
      into that row after it was done (a tail, S5, or a source that filled an
      early translation, S1/S2) and came less than LEAD_S ago, or the row's
      source stops mid-clause -> append: the model is still translating that
      source, in a second sentence. The row then holds several English
      sentences for one Japanese sentence. This also heals a wrong guess: a
      source put beside the wrong translation pulls its own translation in
      after it, so rows can grow but never shift.
  T3. Otherwise -> a new row.
  When the row's translation ends a sentence (. ? !), it is done.

Source chunk:
  S1. Late source: two or more rows at the end have a translation and no source
      (the source of several English sentences arrives at once) -> split the
      chunk at its clause ends and spread it over those rows in order, by
      length (a monotonic alignment); never to a row after them.
  S2. The last row has a translation and no source -> append to it.
  S3. The last row's translation is not done -> append, unless it has a
      translation and both streams were silent for GAP_S -> new row.
      A source-only row that got no translation for DROP_S and is at a clause
      end is given up (untranslated); the chunk opens a new row.
  S4. The last row's translation is done and its source ends at a clause end
      (、。？！) -> a new row; the translation that follows will join it.
  S5. Otherwise the row's source stopped mid-clause: the chunk's text up to
      its first clause end is the row's tail when it comes within TAIL_S of
      the translation's end and is short (TAIL_UNITS); the rest opens a new
      row. A long or late chunk opens a new row whole.

Nothing is ever dropped: every chunk lands, whole or split, in rows in arrival
order. A row is final SEAL_S after its last change; a row with a translation
and no source waits LATE_S for a late source first.

Ops are the fields of one `transcript` event each, the same as v1:
    {"kind", "text", "row", "row_text"}
`text` is the chunk (or piece of it) added and `row_text` the whole side of
the row after it, so the app only sets it. v2 never emits `merge_into`."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

SENTENCE_END = tuple(".?!。？！")
CLAUSE_END = tuple("、。？！，,.?!")

LEAD_S = 2.0        # a translation follows its source chunk by 0.26-0.52 s (measured); this is the bound
TAIL_S = 2.5        # a source tail may finish a row this long after its translation ended
TAIL_UNITS = 6.0    # ... and be at most this long (12 CJK characters)
GAP_S = 3.0         # both streams silent this long: the next source starts a row
ROW_MAX_UNITS = 80  # T2 without a tail stops growing a row whose source is this long (160 CJK characters)
DROP_S = 5.0        # a source with no translation for this long is given up at its next clause end
LATE_S = 30.0       # a translation-only row waits this long for a late source
SEAL_S = 12.0       # a row this long untouched can no longer change; it is saved

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯ｦ-ﾟ]")
_CJK_ANY = "぀-ヿ㐀-䶿一-鿿豈-﫿가-힯　-〿＀-￯"  # letters and CJK/fullwidth punctuation
_SPACE_NEAR_CJK = re.compile(rf"(?<=[{_CJK_ANY}]) +| +(?=[{_CJK_ANY}])")
_WORD = re.compile(r"[A-Za-z0-9À-ɏ'’]+")
_CLAUSE_SPLIT = re.compile(r"(?<=[、。？！，,.?!])")


def units(text: str) -> float:
    """Rough spoken length: one per word, a half per CJK character."""
    return len(_WORD.findall(text)) + 0.5 * len(_CJK.findall(text))


def fit(dst: str, src: str) -> float:
    """|log| of the smoothed length ratio: 0 = same length, larger = worse."""
    return abs(math.log((units(dst) + 1) / (units(src) + 1)))


def clean(text: str) -> str:
    """Whitespace collapsed, no space next to CJK text."""
    return _SPACE_NEAR_CJK.sub("", " ".join(text.split()))


def join_chunks(chunks: list[str]) -> str:
    """Chunks as sent, which carry their own spaces, except that a chunk starting a new
    sentence comes without one ("...today." + "Let's start"): a space goes there."""
    out = ""
    for c in chunks:
        if out and c and out[-1] in ".?!,;:" and (c[0].isascii() and c[0].isalpha() or c[0] in "\"'"):
            out += " "
        out += c
    return clean(out)


def ended(text: str, ends=SENTENCE_END) -> bool:
    return text.rstrip().endswith(ends)


def align(pieces: list[str], targets: list[str]) -> list[list[str]]:
    """Splits `pieces` (in order) into len(targets) contiguous groups, minimising
    the summed length misfit of each group against its target. Groups may be empty."""
    n, k = len(pieces), len(targets)
    inf = float("inf")
    cost = [[inf] * (k + 1) for _ in range(n + 1)]
    back = [[0] * (k + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for j in range(1, k + 1):
        for i in range(n + 1):
            for h in range(i + 1):
                c = cost[h][j - 1] + fit(targets[j - 1], "".join(pieces[h:i]))
                if c < cost[i][j]:
                    cost[i][j], back[i][j] = c, h
    groups, i = [], n
    for j in range(k, 0, -1):
        h = back[i][j]
        groups.append(pieces[h:i])
        i = h
    return groups[::-1]


@dataclass
class Row:
    id: int
    utt: int
    first: float
    last: float
    src: list[str] = field(default_factory=list)   # chunks, as sent
    dst: list[str] = field(default_factory=list)
    src_at: float | None = None    # first source chunk
    dst_at: float | None = None    # last translation chunk
    done_at: float | None = None   # the translation ended a sentence
    tail: float = 0.0              # source units added after the translation was done
    tail_chunks: int = 0           # source chunks added after the translation was done (T2)
    missed: bool = False           # given up waiting for a translation

    @property
    def src_text(self) -> str:
        return join_chunks(self.src)

    @property
    def dst_text(self) -> str:
        return join_chunks(self.dst)

    @property
    def done(self) -> bool:
        return self.done_at is not None

    @property
    def waiting(self) -> bool:
        return bool(self.src) and not self.dst and not self.missed

    def touch(self, at: float) -> None:
        self.first, self.last = min(self.first, at), max(self.last, at)


class Pairer:
    chunks = True  # Direction feeds every transcription chunk, not sentences

    def __init__(self, on_row=None):
        self.rows: list[Row] = []      # open rows, oldest first; sealed ones are removed
        self.next_id = 1
        self.on_row = on_row           # (Row) once a row is sealed
        self.last_src: tuple[Row, float] | None = None  # the row the latest source chunk went to, and when

    def _new(self, utt: int, at: float) -> Row:
        r = Row(self.next_id, utt, at, at)
        self.next_id += 1
        self.rows.append(r)
        return r

    @staticmethod
    def _op(kind: str, text: str, r: Row) -> dict:
        return {"kind": kind, "text": text, "row": r.id,
                "row_text": r.src_text if kind == "src" else r.dst_text}

    def _put_src(self, r: Row, text: str, at: float) -> dict:
        if r.src_at is None:
            r.src_at = at
        if r.done:
            r.tail_chunks += 1  # its translation is still to come (T2)
        r.src.append(text)
        r.touch(at)
        self.last_src = (r, at)
        return self._op("src", text, r)

    # --- input ---------------------------------------------------------------

    def dst(self, text: str, at: float, utt: int) -> list[dict]:
        if not text.strip():
            return []
        last = self.rows[-1] if self.rows else None
        fresh_tail = (last is not None and last.tail_chunks > 0 and self.last_src is not None
                      and self.last_src[0] is last and at - self.last_src[1] <= LEAD_S)
        if last is not None and not last.missed and not last.done:
            r = last  # T1
        elif last is not None and not last.missed and (fresh_tail or (
                last.src and units(last.src_text) < ROW_MAX_UNITS and not ended(last.src_text, CLAUSE_END))):
            r = last  # T2
            r.done_at, r.tail, r.tail_chunks = None, 0.0, 0
        else:
            r = self._new(utt, at)  # T3
        r.dst.append(text)
        r.dst_at = at
        r.touch(at)
        if ended(r.dst_text):
            r.done_at = at
        return [self._op("dst", text, r)]

    def src(self, text: str, at: float, utt: int) -> list[dict]:
        if not text.strip():
            return []
        late = self._translation_only_tail(at)
        if len(late) >= 2:  # S1
            return self._spread(text, late, at)
        last = self.rows[-1] if self.rows else None
        if last is None or last.missed:
            return [self._put_src(self._new(utt, at), text, at)]
        if late:  # S2: the last row has a translation and no source yet
            return [self._put_src(last, text, at)]
        if not last.done:  # S3
            if last.dst and at - last.last > GAP_S:
                return [self._put_src(self._new(utt, at), text, at)]
            if (not last.dst and last.src_at is not None and at - last.src_at > DROP_S
                    and ended(last.src_text, CLAUSE_END)):
                last.missed = True
                return [self._put_src(self._new(utt, at), text, at)]
            return [self._put_src(last, text, at)]
        if not last.src or ended(last.src_text, CLAUSE_END):  # S4
            return [self._put_src(self._new(utt, at), text, at)]
        return self._tail(last, text, at, utt)  # S5

    def _translation_only_tail(self, at: float) -> list[Row]:
        """Rows at the end with a translation and no source, recent enough to take a late source."""
        out = []
        for r in reversed(self.rows):
            if r.src or not r.dst or r.missed or (r.dst_at is not None and at - r.dst_at > LATE_S):
                break
            out.append(r)
        return out[::-1]

    def _spread(self, text: str, rows: list[Row], at: float) -> list[dict]:
        pieces = [p for p in _CLAUSE_SPLIT.split(text) if p]
        ops = []
        for r, group in zip(rows, align(pieces, [r.dst_text for r in rows])):
            part = "".join(group)
            if part.strip():
                ops.append(self._put_src(r, part, at))
        return ops

    def _tail(self, last: Row, text: str, at: float, utt: int) -> list[dict]:
        m = re.search(r"[、。？！，,.?!]", text)
        head, rest = (text[:m.end()], text[m.end():]) if m else (text, "")
        if at - last.done_at <= TAIL_S and last.tail + units(head) <= TAIL_UNITS:
            last.tail += units(head)
            ops = [self._put_src(last, head, at)]
            if rest.strip():
                ops.append(self._put_src(self._new(utt, at), rest, at))
            return ops
        return [self._put_src(self._new(utt, at), text, at)]

    # --- sealing -------------------------------------------------------------

    def seal(self, now: float, force: bool = False) -> list[dict]:
        """Seals the oldest rows untouched for SEAL_S (a translation-only row: LATE_S),
        all of them with force, in order, passing each to on_row. Returns no ops (v2
        never moves text at sealing; the list keeps v1's interface)."""
        while self.rows:
            r = self.rows[0]
            wait = LATE_S if (r.dst and not r.src and not r.missed) else SEAL_S
            if not (force or now - r.last >= wait):
                break
            self.rows.pop(0)
            if self.on_row is not None:
                self.on_row(r)
        return []
