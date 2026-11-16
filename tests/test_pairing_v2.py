"""Pairing v2 (kana/pairing.py): chunks paired as they stream.

Synthetic sequences reproduce the patterns of the 2026-11-16 call (our own
sentences, never the call's), and two real Gemini Live Translate recordings of
synthetic speech (tests/data/*.events.jsonl, tools/replay_tts.py) are replayed
through the engine's text path (kana/replay.py). Every replay is checked
twice: through the ops the app applies by row id and through the saved rows."""
import asyncio
import contextlib
import re
from pathlib import Path

from kana.pairing import (DROP_S, LATE_S, LEAD_S, ROW_MAX_UNITS, SEAL_S, TAIL_S, Pairer, align, clean,
                          units)
from kana.pairing_v1 import Pairer as PairerV1
from kana.replay import App, load, logged_ops, replay
from kana.session import Direction
from tests.test_events import Rec
from tests.test_session import content, resp, wait_for
from tests.test_utterances import LiveFake, connector

DATA = Path(__file__).parent / "data"


def run(events, end=None, pairer=Pairer):
    """events: (time, "src"|"dst", chunk). Seals everything at the end (or checks
    sealing at `end`). Returns the saved rows, which must equal the app's view."""
    saved, app, ops = [], App(), []
    p = pairer(on_row=saved.append)
    for at, kind, text in events:
        for op in (p.src if kind == "src" else p.dst)(text, at, 1):
            ops.append(op)
            app.apply(op)
    for op in p.seal(end if end is not None else 0, force=end is None):
        ops.append(op)
        app.apply(op)
    table = [(r.src_text, r.dst_text) for r in saved]
    if end is None:
        assert app.table() == table, "the app and the saved transcript disagree"
    return table, ops, p


def stream(*pairs, start=0.0, step=1.0, lead=0.3):
    """Interleaves (source chunk, translation chunk) pairs the way Live Translate sends
    them: a source chunk every `step` s, its translation `lead` s later. None skips one."""
    out, t = [], start
    for s, d in pairs:
        if s is not None:
            out.append((t, "src", s))
        if d is not None:
            out.append((t + lead, "dst", d))
        t += step
    return out


def bare(text):
    return re.sub(r"\s", "", text)


def nothing_dropped(events, table):
    """Every chunk is in the rows, in order (spacing aside)."""
    assert bare("".join(r[0] for r in table)) == bare("".join(t for _, k, t in events if k == "src"))
    assert bare("".join(r[1] for r in table)) == bare("".join(t for _, k, t in events if k == "dst"))


# --- the measured stream: 1:1 interleaved chunks ---------------------------------

LONG_TURN = stream(  # a run-on turn: no 。 for 12 s, while the English ends sentences
    ("先週から", "Since last"), ("少しずつ", " week, little by"), ("進めていて、", " little, we've been working on it,"),
    ("届いたファイルが", " and the files we got"), ("ばらばらだったので、", " were all different, so"),
    ("まず揃えてから", " first we lined them up,"), ("手で直していて、", " fixing them by hand."),
    ("今は半分", "Now we are about"), ("ぐらいまで来ている", " halfway there,"), ("んですが、", " but"),
    ("残りは型番が", " the rest have model"), ("違うものが多いです。", " numbers that differ."),
    ("はい。", "Yes."),
    ("それでは", "Then"), ("一覧をいただけますか？", " could you send us the list?"),
)


def test_run_on_turn_is_paired_as_it_streams():
    table, ops, _ = run(LONG_TURN)
    assert table == [
        ("先週から少しずつ進めていて、届いたファイルがばらばらだったので、まず揃えてから手で直していて、",
         "Since last week, little by little, we've been working on it, and the files we got were all different, "
         "so first we lined them up, fixing them by hand."),
        ("今は半分ぐらいまで来ているんですが、残りは型番が違うものが多いです。",
         "Now we are about halfway there, but the rest have model numbers that differ."),
        ("はい。", "Yes."),
        ("それでは一覧をいただけますか？", "Then could you send us the list?"),
    ]
    nothing_dropped(LONG_TURN, table)
    assert all("merge_into" not in op for op in ops)
    # The first row shows both sides from its first second: the source is never held back.
    assert ops[0] == {"kind": "src", "text": "先週から", "row": 1, "row_text": "先週から"}
    assert ops[1] == {"kind": "dst", "text": "Since last", "row": 1, "row_text": "Since last"}


def test_v1_fed_the_same_speech_as_sentences_gives_the_late_source_the_next_translation():
    """The 2026-11-16 defect: v1 sees the run-on source only when 。 finally comes (here
    11 s after its first word) and gives it the translation that follows."""
    sentences = [(0.3, "dst", "Since last week, little by little, we've been working on it, and the files we got "
                              "were all different, so first we lined them up, fixing them by hand."),
                 (8.6, "dst", "Now we are about halfway there, but the rest have model numbers that differ."),
                 (11.0, "src", "先週から少しずつ進めていて、届いたファイルがばらばらだったので、まず揃えてから手で直していて、"
                               "今は半分ぐらいまで来ているんですが、残りは型番が違うものが多いです。"),
                 (12.0, "src", "はい。"), (12.3, "dst", "Yes."),
                 (14.0, "src", "それでは一覧をいただけますか？"), (14.3, "dst", "Then could you send us the list?")]
    table, _, _ = run(sentences, pairer=PairerV1)
    long_row = next(r for r in table if "先週から" in r[0])
    assert "Since last week" not in long_row[1]  # the late source sits beside another translation
    assert ("", "Since last week, little by little, we've been working on it, and the files we got were all "
                "different, so first we lined them up, fixing them by hand.") in table
    table2, _, _ = run(LONG_TURN)
    assert "Since last week" in next(r for r in table2 if "先週から" in r[0])[1]


def test_back_channels_between_long_turns_get_their_own_rows():
    ev = stream(("予算は", "The budget"), ("来月決まります。", " will be decided next month."),
                ("はい。", "Yes."), ("そうですね。", "That's right."),
                ("なので", "So"), ("それまでお待ちください。", " please wait until then."),
                ("うん。", "Yeah."))
    table, _, _ = run(ev)
    assert table == [("予算は来月決まります。", "The budget will be decided next month."), ("はい。", "Yes."),
                     ("そうですね。", "That's right."), ("なのでそれまでお待ちください。", "So please wait until then."),
                     ("うん。", "Yeah.")]


def test_split_translation_stays_in_one_row():
    """One Japanese sentence translated as two English sentences, the second after its
    verb-final tail arrived: one row, both sentences."""
    ev = [(0.0, "src", "その件は"), (0.3, "dst", "About that,"), (1.0, "src", "確認してから"),
          (1.3, "dst", " we will check."), (2.0, "src", "お返事"), (2.3, "dst", "Then we"),
          (3.0, "src", "します。"), (3.3, "dst", " will reply."), (4.0, "src", "はい。"), (4.3, "dst", "Okay.")]
    table, _, _ = run(ev)
    assert table == [("その件は確認してからお返事します。", "About that, we will check. Then we will reply."),
                     ("はい。", "Okay.")]


def test_verb_final_tail_joins_the_finished_row_and_the_rest_starts_the_next():
    ev = [(0.0, "src", "ご相談させて"), (0.3, "dst", "Let us discuss it."),
          (1.0, "src", "ください。あと、"), (1.3, "dst", "Also,"), (2.0, "src", "日程ですが、"),
          (2.3, "dst", " about the schedule,"), (3.0, "src", "火曜日でお願いします。"), (3.3, "dst", " Tuesday please.")]
    table, ops, _ = run(ev)
    assert table == [("ご相談させてください。", "Let us discuss it."),
                     ("あと、日程ですが、火曜日でお願いします。", "Also, about the schedule, Tuesday please.")]
    assert [(o["row"], o["text"]) for o in ops if o["kind"] == "src"][1:3] == [(1, "ください。"), (2, "あと、")]


def test_translation_of_a_tail_follows_its_source():
    """A second English sentence that translates the tail (it arrives right after it)
    stays with that tail's row, not with the next speaker's back-channel."""
    ev = [(0.0, "src", "メールでご相談させて"), (0.3, "dst", "I'll contact you by email."),
          (1.0, "src", "ください。"), (1.3, "dst", "Please let me know."),
          (2.0, "src", "分かりました。"), (2.3, "dst", "Understood.")]
    table, _, _ = run(ev)
    assert table == [("メールでご相談させてください。", "I'll contact you by email. Please let me know."),
                     ("分かりました。", "Understood.")]


def test_translation_of_a_tail_follows_it_even_in_a_very_long_row():
    """Seen live (tests/data/2026-11-16-tts-runon-2): a turn longer than ROW_MAX_UNITS ended
    with a verb-final tail and one more English sentence for it. That sentence must join the
    long row, or every following back-channel row shifts by one."""
    words = ["データを", "取り込んで", "いて、", "形式を", "揃えて", "います。"] * 9
    ev = []
    for k, w in enumerate(words[:-1]):
        ev += [(k * 1.0, "src", w), (k * 1.0 + 0.3, "dst", f" part{k}")]
    n = len(words) - 1
    ev[-1] = (ev[-1][0], "dst", ev[-1][2] + ".")  # the English ends; the Japanese still lacks its tail
    ev += [(n + 0.0, "src", "います。"), (n + 0.4, "dst", "Right?"),
           (n + 1.0, "src", "そうですね。"), (n + 1.3, "dst", "That's right."),
           (n + 3.0, "src", "なるほど。"), (n + 3.3, "dst", "I see.")]
    table, _, _ = run(ev)
    assert units(table[0][0]) > ROW_MAX_UNITS and table[0][1].endswith(". Right?")
    assert table[1:] == [("そうですね。", "That's right."), ("なるほど。", "I see.")]


def test_a_wrong_guess_grows_a_row_instead_of_shifting_the_next_ones():
    """A translation that comes too late to follow its source opens a translation-only row,
    and the next source fills it (wrongly). Its own translation then follows it into that
    row (T2), so the rows after it are still right."""
    ev = [(0.0, "src", "時間がかかりそうです。"), (0.3, "dst", "It will take time."),
          (0.3 + LEAD_S + 1.0, "dst", "Right?"),
          (0.3 + LEAD_S + 1.5, "src", "そうですね。"), (0.3 + LEAD_S + 1.8, "dst", "That's right."),
          (0.3 + LEAD_S + 3.5, "src", "なるほど。"), (0.3 + LEAD_S + 3.8, "dst", "I see.")]
    table, _, _ = run(ev)
    assert table == [("時間がかかりそうです。", "It will take time."), ("そうですね。", "Right? That's right."),
                     ("なるほど。", "I see.")]


def test_early_translation_is_filled_by_its_source():
    ev = [(0.0, "dst", "Good morning."), (0.4, "src", "おはようございます。"),
          (2.0, "src", "始めます。"), (2.3, "dst", "Let's start.")]
    table, _, _ = run(ev)
    assert table == [("おはようございます。", "Good morning."), ("始めます。", "Let's start.")]


def test_late_n_to_1_source_chunk_is_spread_over_its_translations_in_order():
    """A provider that sends the source of several sentences at once, after their
    translations: the chunk is split at its clause ends and aligned by length."""
    ev = [(0.0, "dst", "Thank you for coming today."),
          (3.0, "dst", "We will explain the new pricing plan, which starts in April, and the changes to support."),
          (9.0, "dst", "Yes."),
          (20.0, "src", "本日はお越しいただきありがとうございます。四月から始まる新しい料金プランとサポートの変更について"
                        "ご説明します。はい。"),
          (22.0, "src", "では"), (22.3, "dst", "Well then,"), (23.0, "src", "始めましょう。"), (23.3, "dst", " let's begin.")]
    table, ops, _ = run(ev)
    assert table == [("本日はお越しいただきありがとうございます。", "Thank you for coming today."),
                     ("四月から始まる新しい料金プランとサポートの変更についてご説明します。",
                      "We will explain the new pricing plan, which starts in April, and the changes to support."),
                     ("はい。", "Yes."),
                     ("では始めましょう。", "Well then, let's begin.")]
    nothing_dropped(ev, table)


def test_late_source_never_goes_to_rows_older_than_late_s():
    ev = [(0.0, "dst", "First sentence here."), (LATE_S + 5, "dst", "Second one."),
          (LATE_S + 6, "dst", "Third one."), (LATE_S + 7, "src", "二つ目です。三つ目です。")]
    table, _, _ = run(ev)
    assert table == [("", "First sentence here."), ("二つ目です。", "Second one."), ("三つ目です。", "Third one.")]


def test_dropped_translation_leaves_the_source_alone_and_moves_on():
    """The model said nothing for a stretch (e.g. it was already English): after DROP_S
    the source-only row is given up at its clause end; the next speech gets its own row."""
    ev = [(0.0, "src", "ちょっと"), (1.0, "src", "待ってください、"), (2.0, "src", "えーと"),
          (3.0, "src", "あの資料、"), (DROP_S + 1.0, "src", "それで"), (DROP_S + 1.3, "dst", "So,"),
          (DROP_S + 2.0, "src", "本題です。"), (DROP_S + 2.3, "dst", " to the main point.")]
    table, _, p = run(ev)
    assert table == [("ちょっと待ってください、えーとあの資料、", ""), ("それで本題です。", "So, to the main point.")]
    nothing_dropped(ev, table)


def test_silence_starts_a_new_row_even_mid_sentence():
    ev = [(0.0, "src", "それで"), (0.3, "dst", "And then the"), (5.0, "src", "次の議題です。"), (5.3, "dst", "Next topic.")]
    table, _, _ = run(ev)
    assert table == [("それで", "And then the"), ("次の議題です。", "Next topic.")]


def test_a_long_tail_or_a_late_one_opens_a_new_row():
    ev = [(0.0, "src", "その件は"), (0.3, "dst", "About that."),
          (1.0, "src", "社内でもう一度しっかり検討してから"), (1.3, "dst", "We will review it again internally"),
          (2.0, "src", "決めます。"), (2.3, "dst", " before deciding.")]
    table, _, _ = run(ev)
    assert table[0] == ("その件は", "About that.")
    ev2 = [(0.0, "src", "その件は"), (0.3, "dst", "About that."), (0.3 + TAIL_S + 0.5, "src", "はい。"),
           (0.3 + TAIL_S + 0.8, "dst", "Yes.")]
    assert run(ev2)[0] == [("その件は", "About that."), ("はい。", "Yes.")]


def test_sealing_waits_longer_for_a_translation_only_row():
    saved = []
    p = Pairer(on_row=saved.append)
    p.src("はい。", 0.0, 1)
    p.dst("Yes.", 0.3, 1)
    p.dst("Hello there.", 1.0, 1)  # its source never comes
    p.seal(SEAL_S + 1.0)
    assert [(r.src_text, r.dst_text) for r in saved] == [("はい。", "Yes.")]
    assert len(p.rows) == 1  # a late source may still come for the translation-only row
    p.seal(LATE_S + 0.5)
    assert len(p.rows) == 1
    p.seal(LATE_S + 1.5)
    assert [(r.src_text, r.dst_text) for r in saved][1] == ("", "Hello there.") and not p.rows


def test_whitespace_next_to_japanese_is_dropped_and_english_spacing_kept():
    assert clean("そうですね 、 はい 。") == "そうですね、はい。"
    assert clean("Thank you" + " for coming.") == "Thank you for coming."
    assert clean("ええ 、this is the same やつ") == "ええ、this is the sameやつ"
    assert units("はい。") == 1.0


def test_align_is_monotonic_and_covers_every_piece():
    pieces = ["ありがとうございます。", "四月から新しい料金プランが始まります。", "はい。"]
    groups = align(pieces, ["Thank you.", "A new pricing plan starts in April.", "Yes."])
    assert groups == [[pieces[0]], [pieces[1]], [pieces[2]]]
    groups = align(pieces, ["Thanks.", "Okay."])
    assert sum(groups, []) == pieces and len(groups) == 2


# --- the engine feeds chunks -----------------------------------------------------

async def test_direction_feeds_each_chunk_to_the_pairer():
    rec, saved = Rec(), []
    s = LiveFake()
    connect, _ = connector([s])
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect, emit=rec,
                  on_row=lambda _d, r: saved.append((r.src_text, r.dst_text)))
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        for c in (content(inp="今日は"), content(outp="Today"), content(inp="晴れです。"), content(outp=" it's sunny.")):
            s.q.put_nowait(resp(server_content=c))
        await wait_for(lambda: len(rec.of("transcript")) == 4)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert [(t["kind"], t["text"], t["row"], t["row_text"]) for t in rec.of("transcript")] == [
        ("src", "今日は", 1, "今日は"), ("dst", "Today", 1, "Today"),
        ("src", "晴れです。", 1, "今日は晴れです。"), ("dst", " it's sunny.", 1, "Today it's sunny.")]
    assert saved == [("今日は晴れです。", "Today it's sunny.")]


async def test_terminal_mode_still_prints_whole_sentences():
    lines = []
    s = LiveFake()
    connect, _ = connector([s])
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), connect=connect, out=lines.append)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        for c in (content(inp="今日は"), content(outp="Today"), content(inp="晴れです。"), content(outp=" it's sunny.")):
            s.q.put_nowait(resp(server_content=c))
        await wait_for(lambda: len(lines) == 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    assert lines == ["[IN ja->en] 今日は晴れです。", "[IN ja->en] => Today it's sunny."]


# --- replays of real Live Translate sessions (synthetic speech) ------------------

def anchored(rows, anchors):
    """Each (Japanese fragment, English fragment) must sit in one row. Returns the misses."""
    misses = []
    for ja, en in anchors:
        hits = [r for r in rows if ja in r[0]]
        assert hits, f"no row has {ja!r}"
        if not any(en in r[1] for r in hits):
            misses.append((ja, en))
    return misses


RUNON_ANCHORS = [  # tools/replay_tts.py --script runon, run on 2026-11-16
    ("データのこと", "about the data"), ("半分ぐらい", "halfway"), ("時間がかかり", "take a while"),
    ("そうですね。", "Yes, that's right."), ("なるほど。", "I see."), ("準備して", "prepare in advance"),
    ("あ、そうですね", "Oh, that's right"), ("型番の一覧", "list of model numbers"), ("突き合わせ", "match them"),
    ("間違いも", "reduce errors"), ("是非お願い", "appreciate"), ("ロゴ", "logos"), ("保留", "on hold"),
    ("来週を返事", "next week"), ("定例", "regular meeting"), ("ご相談させてください", "Please let me know"),
    ("分かりました。", "Understood."), ("進めましょう", "proceed"),
]
RUNON2_ANCHORS = [  # the same script, run again (the model's wording differs)
    ("データの話", "about the data"), ("半分ぐらい", "halfway"), ("時間がかかり", "longer than expected"),
    ("そうですね。", "That's right."), ("なるほど。", "I see."), ("準備して", "prepare in advance"),
    ("あ、そうですね", "Oh, that's right"), ("型番の一覧", "list of model numbers"), ("突き合わせ", "cross-reference"),
    ("間違いも", "reduce errors"), ("是非お願い", "appreciate"), ("ロゴ", "logo"), ("保留", "on hold"),
    ("来週を返事", "next week"), ("定例", "regular meeting"), ("分かりました。", "Understood."),
    ("進めましょう", "proceed"),
]
CLEAN_ANCHORS = [  # tools/replay_tts.py --script clean
    ("お忙しい", "busy schedule"), ("進捗", "progress"), ("3000件", "3,000"), ("カタログ", "catalog"),
    ("型番の書き方", "model numbers"), ("人の確認", "human verification"), ("承認", "approve"),
    ("なるほど。", "I see."), ("助かります", "helpful"), ("9割", "90%"), ("写真", "photos"),
    ("分かりました。", "I understand."), ("月額", "monthly"), ("初期の設定", "setup fee"), ("弊社側で2名", "two people"),
    ("定例", "regular meeting"), ("承知しました。", "I understand."), ("担当者", "person in charge"),
    ("失礼いたします", "take my leave"),
]


def check_replay(path, anchors):
    ev = load(path)
    res = replay(ev, "in")
    assert res.rows == res.app.table(), "the app and the saved transcript disagree"
    assert anchored(res.rows, anchors) == []
    # every English row has its own Japanese
    assert all(src for src, dst in res.rows if dst), [r for r in res.rows if r[1] and not r[0]]
    # nothing dropped: all chunks are in the rows, in order
    for kind, side in (("input_transcription", 0), ("output_transcription", 1)):
        chunks = bare("".join(e["text"] for e in ev if e.get("dir") == "in" and e["ev"] == kind))
        assert bare("".join(r[side] for r in res.rows)) == chunks
    return ev, res


def test_replay_run_on_session_pairs_every_row():
    ev, res = check_replay(DATA / "2026-11-16-tts-runon.events.jsonl", RUNON_ANCHORS)
    assert len(res.rows) == 15
    v1 = replay(ev, "in", pairer_factory=PairerV1)
    assert len(anchored(v1.rows, RUNON_ANCHORS)) >= 8  # v1 shows the call's defect on the same audio
    assert sum(1 for s, d in v1.rows if d and not s) >= 10


def test_replay_second_run_on_session_fixes_what_the_live_engine_showed():
    """Recorded with the first v2 (ROW_MAX_UNITS also blocked a tail's translation): live,
    three back-channel rows were shifted by one. The replay with the current rules is right."""
    ev, res = check_replay(DATA / "2026-11-16-tts-runon-2.events.jsonl", RUNON2_ANCHORS)
    live = App()
    for op in logged_ops(ev, "in"):
        live.apply(op)
    assert ("そうですね。", "Right?") in live.table()
    assert [r for r in res.rows if units(r[0]) <= 3][:3] == [
        ("そうですね。", "That's right."), ("なるほど。", "I see."), ("あ、そうですね。", "Oh, that's right.")]


def test_replay_clean_session_pairs_every_row():
    ev, res = check_replay(DATA / "2026-11-16-tts-clean.events.jsonl", CLEAN_ANCHORS)
    assert 20 <= len(res.rows) <= 30


def test_replay_back_channel_rows_are_exact():
    _, res = check_replay(DATA / "2026-11-16-tts-runon.events.jsonl", RUNON_ANCHORS)
    short = [r for r in res.rows if units(r[0]) <= 3]
    assert short == [("そうですね。", "Yes, that's right."), ("なるほど。", "I see."),
                     ("あ、そうですね。", "Oh, that's right."), ("はい。", "Yes."), ("はい。", "Yes."),
                     ("分かりました。", "Understood.")]
    assert not any(re.search(r"\s[、。]", r[0]) for r in res.rows)
