"""Inbound speech already in the listener's language (room audio coming back on the
meeting) is transcribed and paired but not re-voiced (--voice-own-language off)."""
import asyncio
import contextlib
import json

from kana import __main__ as cli
from kana.eventlog import EventLog
from kana.session import Direction, own_language_checker
from tests.test_events import Rec
from tests.test_session import content, resp, wait_for
from tests.test_utterances import LiveFake, connector

LOUD = b"\0\x10" * 480


def test_checker_needs_three_latin_words_that_outweigh_any_other_script():
    check = own_language_checker("en", "ja")
    assert check("Can you") is None                      # not enough yet
    assert check("Can you share the screen") is True
    assert check("はい、そうですね") is False
    assert check("はい。") is None                        # a back-channel alone: undecided, played as usual
    assert check("VAIOの件ですが、来週お送りします") is False  # a Latin brand name inside Japanese
    assert check("3,000 items") is None                  # numbers are not words
    # measured: the Japanese ASR writes the first English word in kana
    assert check("オッケー。 I can see it") is True
    assert check("さり、could you share") is True
    assert own_language_checker("en", "zh")("我们可以下周再讨论 okay") is False


def test_checker_is_off_where_script_cannot_tell_the_languages_apart():
    assert own_language_checker("en", "es") is None      # both Latin script
    assert own_language_checker("ja", "en") is None      # a CJK listener: not checked (yet)
    assert own_language_checker("en-US", "ja-JP") is not None


async def _run(chunks, voice_own=False, tmp_path=None):
    """chunks: list of ("in"|"out"|"audio"|"onset", text). Returns (rec, audio chunks played, d)."""
    rec = Rec()
    s = LiveFake()
    connect, _ = connector([s])
    out_q = asyncio.Queue()
    log = EventLog(tmp_path / "e.jsonl") if tmp_path else None
    d = Direction("IN", "ja", "en", "m-translate", asyncio.Queue(), out_q, connect=connect, emit=rec,
                  own_language=own_language_checker("en", "ja"), voice_own_language=voice_own,
                  log=log.for_dir("in") if log else None)
    task = asyncio.create_task(d.run())
    try:
        await wait_for(lambda: d.session is s)
        for kind, text in chunks:
            if kind == "onset":
                d._onset()
                continue
            c = {"in": content(inp=text), "out": content(outp=text), "audio": content(audio=LOUD)}[kind]
            s.q.put_nowait(resp(server_content=c))
            await wait_for(lambda: s.q.empty())
            for _ in range(5):
                await asyncio.sleep(0)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if log:
            log.close()
    return rec, out_q.qsize(), d


def tr(rec):
    return [(t["kind"], t["text"], t.get("echo")) for t in rec.of("transcript")]


async def test_english_from_the_room_is_paired_but_not_played(tmp_path):
    rec, played, d = await _run([("in", "Can you share"), ("audio", ""), ("out", "Can you share"),
                                 ("in", " the screen?"), ("audio", ""), ("out", " the screen?")], tmp_path=tmp_path)
    assert played == 0 and d.echo_dropped_bytes == 2 * len(LOUD)
    assert tr(rec) == [("src", "Can you share", True), ("dst", "Can you share", True),
                       ("src", " the screen?", True), ("dst", " the screen?", True)]
    log = [json.loads(l) for l in open(tmp_path / "e.jsonl")]
    echo = [e for e in log if e["ev"] == "echo"]
    assert echo == [{"t": echo[0]["t"], "dir": "in", "ev": "echo", "seq": 1, "echo": True, "play": False,
                     "words": 3}]
    assert all(e["echo"] for e in log if e["ev"] == "transcript")


async def test_japanese_is_played_and_carries_no_echo_field():
    rec, played, d = await _run([("in", "画面を共有して"), ("audio", ""), ("out", "Could you share"),
                                 ("in", "いただけますか？"), ("audio", ""), ("out", " your screen?")])
    assert played == 2 and d.echo_dropped_bytes == 0
    assert all(e is None for _, _, e in tr(rec))


async def test_audio_before_the_decision_is_played():
    """The decision needs three words; audio that came before it has already gone out."""
    rec, played, _ = await _run([("in", "Okay"), ("audio", ""), ("in", " so the next"), ("audio", ""),
                                 ("audio", "")])
    assert played == 1


async def test_voice_own_language_on_plays_it_but_still_marks_it():
    rec, played, _ = await _run([("in", "Can you share the screen?"), ("audio", ""),
                                 ("out", "Can you share the screen?")], voice_own=True)
    assert played == 1 and [e for _, _, e in tr(rec)] == [True, True]


async def test_meeting_language_after_an_english_start_is_played_again():
    """Mixed speech without a pause (one utterance): an English start, then Japanese.
    From the first Japanese chunk on, audio plays and the row's events say echo false."""
    rec, played, _ = await _run([("in", "Okay, so let's start"), ("audio", ""), ("out", "Okay, so let's start."),
                                 ("in", "では始めます。"), ("audio", ""), ("out", "Let's begin.")])
    assert played == 1
    flags = [e for _, _, e in tr(rec)]
    assert flags[:2] == [True, True] and flags[-1] is False


async def test_each_utterance_is_decided_afresh():
    rec, played, _ = await _run([("in", "Can you hear me?"), ("audio", ""), ("out", "Can you hear me?"),
                                 ("onset", ""),
                                 ("in", "はい、聞こえます。"), ("audio", ""), ("out", "Yes, I can hear you.")])
    assert played == 1
    t = rec.of("transcript")
    assert [x.get("echo") for x in t if x["row"] == 1] == [True, True]
    assert [x.get("echo") for x in t if x["row"] != 1] == [None, None]


def test_flag_defaults_to_off():
    assert cli.parse_args([]).voice_own_language == "off"
    assert cli.parse_args(["--voice-own-language", "on"]).voice_own_language == "on"


def test_live_recording_english_utterances_are_found_and_japanese_ones_not():
    """tests/data/2026-11-16-tts-mixed: Japanese turns (Kyoko) and English from the room
    (Samantha) through the real model; utterances 2, 4 and 6 are the English ones."""
    from pathlib import Path
    from kana.replay import load
    check = own_language_checker("en", "ja")
    ev = load(Path(__file__).parent / "data" / "2026-11-16-tts-mixed.events.jsonl")
    seq, heard, verdict = None, {}, {}
    for e in ev:
        if e.get("dir") != "in":
            continue
        if e["ev"] == "utterance_open":
            seq = e["seq"]
        elif e["ev"] == "input_transcription" and seq not in verdict:
            heard[seq] = heard.get(seq, "") + e["text"]
            v = check(heard[seq])
            if v is not None:
                verdict[seq] = v
    assert {k for k, v in verdict.items() if v} == {2, 4, 6}
    assert all(verdict.get(k) in (False, None) for k in (1, 3, 5, 7))
