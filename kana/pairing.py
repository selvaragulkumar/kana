"""Pairs source sentences with their translations into rows, by timing and
length rather than strict order.

The model does not translate sentence by sentence. It folds a short tag
("Right?", 「ですよね」) into the translation before it, splits one long
sentence into two translations, drops a translation now and then, and
sometimes finishes a translation before the source transcript arrives. Pairing
strictly in order lets one such event shift every later row.

One Pairer per direction. Each sentence goes in with the time it was
finalised and the utterance it was heard in; out come ops, each the fields of
one `transcript` event:

    {"kind", "text", "row", "row_text"}                  text added to `row`
    {"kind": "src", "text", "row", "merge_into", "row_text"}
                                                          row `row` (a lone
                                                          src) is removed and
                                                          its text appended to
                                                          `merge_into`

`row_text` is the whole side of the receiving row after the change, so the app
only sets it. Rows are numbered from 1 per direction, in the order opened.

Rules for a translation (dst) arriving, in this order:
1. Continue: the last row's translation has no sentence end yet -> append.
2. Nothing waiting for a translation: a split (the last row's translation is
   still short of its source and arrived moments ago) -> append; else a
   translation-only row, which the next source fills when the lengths fit.
3. Fold: while two or more sources wait, the oldest is short (<= 3 words or
   6 CJK characters), the same utterance as the row above, ended before that
   row's translation arrived, and the new translation fits it badly but fits
   the next one better -> fold it into the row above.
4. Dropped translation: while two or more wait and the oldest is stale (lag +
   3 s old, the next one ended a lag or more after it and at least half a lag
   ago) and the new translation is not a clear length match for the oldest
   but a bad one for the next -> leave the oldest untranslated.
5. Split with sources waiting: the last row's translation is still short of
   its source, the new one completes it, and it fits the oldest waiting
   source badly -> append to the last row.
6. Otherwise -> the oldest waiting source.

Nothing is ever dropped: every sentence lands in exactly one row. Text is only
folded within one utterance."""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

SENTENCE_END = tuple(".?!。？！")

SHORT_UNITS = 3.0      # a "short" source: <= 3 words / 6 CJK characters
POOR_FIT = 2.5         # length ratio (either way) beyond which a pair fits badly
UNDER_COVERED = 0.6    # translation/source length below which a translation looks unfinished
SPLIT_S = 4.0          # a split's second half arrives within this of the first
ORPHAN_FILL_S = 4.0    # a source arriving this soon after a translation-only row may fill it
DEFAULT_LAG_S = 2.0    # source-final to translation-final, before any is measured
STALE_EXTRA_S = 3.0    # a waiting source this much older than the lag counts as stale
SEAL_S = 12.0          # a row this long untouched can no longer change; it is saved

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯ｦ-ﾟ]")
_WORD = re.compile(r"[A-Za-z0-9À-ɏ'’]+")


def units(text: str) -> float:
    """Rough spoken length: one per word, a half per CJK character."""
    return len(_WORD.findall(text)) + 0.5 * len(_CJK.findall(text))


def fit(dst: str, src: str) -> float:
    """|log| of the smoothed length ratio: 0 = same length, larger = worse."""
    return abs(math.log((units(dst) + 1) / (units(src) + 1)))


def join_text(parts: list[str]) -> str:
    """Joins sentences with a space, except where either side is CJK."""
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and not (_CJK.match(out[-1]) or _CJK.match(p[0]) or out[-1] in "。、？！"):
            out += " "
        out += p
    return out


def ended(text: str) -> bool:
    return text.rstrip().endswith(SENTENCE_END)


@dataclass
class Row:
    id: int
    utt: int
    first: float
    last: float
    src: list[str] = field(default_factory=list)
    dst: list[str] = field(default_factory=list)
    src_at: float | None = None   # last source sentence finalised
    dst_at: float | None = None   # last translation sentence finalised
    missed: bool = False          # given up waiting for a translation

    @property
    def src_text(self) -> str:
        return join_text(self.src)

    @property
    def dst_text(self) -> str:
        return join_text(self.dst)

    @property
    def waiting(self) -> bool:
        return bool(self.src) and not self.dst and not self.missed

    def touch(self, at: float) -> None:
        self.first, self.last = min(self.first, at), max(self.last, at)


class Pairer:
    def __init__(self, on_row=None):
        self.rows: list[Row] = []      # open rows, oldest first; sealed ones are removed
        self.next_id = 1
        self.lags: list[float] = []
        self.on_row = on_row           # (Row) once a row is sealed

    # --- helpers -------------------------------------------------------------

    @property
    def lag(self) -> float:
        return statistics.median(self.lags[-9:]) if self.lags else DEFAULT_LAG_S

    def _new(self, utt: int, at: float) -> Row:
        r = Row(self.next_id, utt, at, at)
        self.next_id += 1
        self.rows.append(r)
        return r

    def _above(self, r: Row) -> Row | None:
        i = self.rows.index(r)
        return self.rows[i - 1] if i > 0 else None

    @staticmethod
    def _op(kind: str, text: str, r: Row) -> dict:
        return {"kind": kind, "text": text, "row": r.id,
                "row_text": r.src_text if kind == "src" else r.dst_text}

    def _put_dst(self, r: Row, text: str, at: float) -> dict:
        if not r.dst and r.src_at is not None and at >= r.src_at:
            self.lags.append(at - r.src_at)
        r.dst.append(text)
        r.dst_at = at
        r.touch(at)
        return self._op("dst", text, r)

    # --- input ---------------------------------------------------------------

    def src(self, text: str, at: float, utt: int) -> list[dict]:
        last = self.rows[-1] if self.rows else None
        if (last is not None and last.src and not last.dst and not ended(last.src[-1])
                and last.utt == utt):
            r = last  # the previous source was cut mid-sentence (turn end, reconnect): continue it
        elif (last is not None and last.dst and not last.src and last.dst_at is not None
              and at - last.dst_at <= ORPHAN_FILL_S and fit(last.dst_text, text) < math.log(POOR_FIT)):
            r = last  # the translation arrived before its source
        else:
            r = self._new(utt, at)
        r.src.append(text)
        r.src_at = at
        r.touch(at)
        return [self._op("src", text, r)]

    def dst(self, text: str, at: float, utt: int) -> list[dict]:
        ops: list[dict] = []
        last = self.rows[-1] if self.rows else None
        if last is not None and last.dst and not ended(last.dst[-1]):
            return [self._put_dst(last, text, at)]  # rule 1
        waiting = [r for r in self.rows if r.waiting]
        filled = [r for r in self.rows if r.dst]
        prev = filled[-1] if filled else None
        if not waiting:  # rule 2
            if prev is not None and prev is last and self._split(prev, text, at):
                return [self._put_dst(prev, text, at)]
            r = self._new(utt, at)
            return [self._put_dst(r, text, at)]
        while len(waiting) >= 2 and self._foldable(waiting[0], text, waiting[1]):  # rule 3
            ops.append(self._fold(waiting.pop(0)))
        while len(waiting) >= 2 and self._stale(waiting[0], waiting[1], text, at):  # rule 4
            waiting.pop(0).missed = True
        head = waiting[0]
        prev = max((r for r in self.rows if r.dst and r.id < head.id), key=lambda r: r.id, default=None)
        if (prev is not None and self._split(prev, text, at)
                and fit(text, head.src_text) > math.log(POOR_FIT)):  # rule 5
            ops.append(self._put_dst(prev, text, at))
        else:  # rule 6
            ops.append(self._put_dst(head, text, at))
        return ops

    def _split(self, prev: Row, text: str, at: float) -> bool:
        """`text` looks like the second half of prev's translation."""
        if not prev.src or prev.dst_at is None or at - prev.dst_at > SPLIT_S:
            return False
        src_u = units(prev.src_text) + 1
        now = (units(prev.dst_text) + 1) / src_u
        after = (units(prev.dst_text) + units(text) + 1) / src_u
        return now < UNDER_COVERED and abs(math.log(after)) < abs(math.log(now))

    def _foldable(self, p: Row, text: str, nxt: Row) -> bool:
        above = self._above(p)
        return (above is not None and bool(above.dst) and bool(above.src) and above.utt == p.utt
                and above.dst_at is not None and p.src_at is not None and p.src_at < above.dst_at
                and units(p.src_text) <= SHORT_UNITS
                and fit(text, p.src_text) > math.log(POOR_FIT)
                and fit(text, nxt.src_text) < fit(text, p.src_text))

    def _fold(self, p: Row) -> dict:
        above = self._above(p)
        above.src.extend(p.src)
        above.src_at = max(above.src_at or p.src_at, p.src_at)
        above.touch(p.first)
        above.touch(p.last)
        self.rows.remove(p)
        op = self._op("src", p.src_text, above)
        op["row"], op["merge_into"] = p.id, above.id
        return op

    def _stale(self, p: Row, nxt: Row, text: str, at: float) -> bool:
        lag = self.lag
        return (at - p.src_at >= lag + STALE_EXTRA_S
                and nxt.src_at - p.src_at >= max(lag, 2.0)
                and at - nxt.src_at >= 0.5 * lag
                and not fit(text, nxt.src_text) > math.log(POOR_FIT) > fit(text, p.src_text))

    # --- sealing -------------------------------------------------------------

    def seal(self, now: float, force: bool = False) -> list[dict]:
        """Seals the oldest rows untouched for SEAL_S (all with force), in order,
        passing each to on_row. Before a row is sealed, a short source right
        after it that never got a translation of its own, and ended before
        this row's translation arrived, is folded into it. Returns the fold ops."""
        ops = []
        while self.rows and (force or now - self.rows[0].last >= SEAL_S):
            r = self.rows[0]
            if len(self.rows) > 1:
                nxt = self.rows[1]
                later = self.rows[2:]
                if (nxt.waiting and (force or now - nxt.last >= SEAL_S) and not any(x.dst for x in later)
                        and r.src and r.dst and r.utt == nxt.utt and r.dst_at is not None
                        and nxt.src_at < r.dst_at and units(nxt.src_text) <= SHORT_UNITS):
                    ops.append(self._fold(nxt))
            self.rows.pop(0)
            if self.on_row is not None:
                self.on_row(r)
        return ops
