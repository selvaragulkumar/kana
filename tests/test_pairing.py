"""Source/translation pairing by timing (kana/pairing.py), replayed from
timed event sequences. Each replay is checked twice: through the ops the app
applies (by row id) and through the rows saved to the transcript files."""
from kana.pairing import SEAL_S, Pairer, join_text, units


class App:
    """Applies transcript ops the way app/Sources/Kana/EngineProcess.swift does."""

    def __init__(self):
        self.rows: dict[int, list[str]] = {}

    def apply(self, op):
        if "merge_into" in op:
            self.rows.pop(op["row"])
            self.rows[op["merge_into"]][0] = op["row_text"]
            return
        row = self.rows.setdefault(op["row"], ["", ""])
        row[0 if op["kind"] == "src" else 1] = op["row_text"]

    def table(self):
        return [tuple(self.rows[k]) for k in sorted(self.rows)]


def replay(events, end=None):
    """events: (time, kind, text[, utterance]). Seals everything at the end
    (`end` = the time of a final seal check instead of a forced one)."""
    saved, app, ops = [], App(), []
    p = Pairer(on_row=saved.append)
    for e in events:
        at, kind, text, utt = (*e, 1) if len(e) == 3 else e
        for op in (p.src if kind == "src" else p.dst)(text, at, utt):
            ops.append(op)
            app.apply(op)
    for op in p.seal(end if end is not None else 0, force=end is None):
        ops.append(op)
        app.apply(op)
    table = [(r.src_text, r.dst_text) for r in saved]
    assert app.table() == table, "the app and the saved transcript disagree"
    return table, ops


LIVE = [  # en->ja, seen live 2026-11-13: the model folded "Right?" into the translation before it
    (1.0, "src", "Hello."), (2.2, "dst", "こんにちは。"),
    (3.5, "src", "Can you hear me?"), (4.8, "dst", "聞こえますか？"),
    (7.0, "src", "I think it's sort of slow."), (7.6, "src", "Right?"),
    (8.6, "dst", "あのちょっと遅い気がしますね。"),
    (10.5, "src", "I don't know how fast it can do this."), (12.0, "dst", "どうやって速くできるかわからないけど。"),
    (13.5, "src", "But yeah, I think it's working."), (15.0, "dst", "でもまあ、動いてると思うけど。"),
]


def test_live_bug_tag_question_folds_into_the_row_above():
    table, ops = replay(LIVE)
    assert table == [
        ("Hello.", "こんにちは。"),
        ("Can you hear me?", "聞こえますか？"),
        ("I think it's sort of slow. Right?", "あのちょっと遅い気がしますね。"),
        ("I don't know how fast it can do this.", "どうやって速くできるかわからないけど。"),
        ("But yeah, I think it's working.", "でもまあ、動いてると思うけど。"),
    ]
    merges = [o for o in ops if "merge_into" in o]
    assert merges == [{"kind": "src", "text": "Right?", "row": 4, "merge_into": 3,
                       "row_text": "I think it's sort of slow. Right?"}]


def test_tag_question_at_the_end_folds_when_sealed():
    table, _ = replay(LIVE[:7])  # "Right?" never gets a translation and nothing follows it
    assert table[-1] == ("I think it's sort of slow. Right?", "あのちょっと遅い気がしますね。")
    assert len(table) == 3


def test_lag_of_one_does_not_merge():
    table, ops = replay([
        (1.0, "src", "We shipped the new build yesterday."),
        (2.0, "src", "Right?"),
        (2.6, "dst", "昨日新しいビルドを出しました。"),
        (3.4, "dst", "ですよね？"),  # the tag translated on its own
        (5.0, "src", "The tests are all green."),
        (6.0, "src", "The deploy went fine."),
        (6.8, "dst", "テストは全部通っています。"),
        (8.0, "dst", "デプロイも問題ありませんでした。"),
    ])
    assert table == [
        ("We shipped the new build yesterday.", "昨日新しいビルドを出しました。"),
        ("Right?", "ですよね？"),
        ("The tests are all green.", "テストは全部通っています。"),
        ("The deploy went fine.", "デプロイも問題ありませんでした。"),
    ]
    assert not any("merge_into" in o for o in ops)


def test_lag_of_two_does_not_merge():
    table, ops = replay([
        (6.0, "src", "Let's look at the price list."),
        (7.0, "src", "Okay."),
        (8.0, "src", "Then the delivery dates."),
        (8.5, "dst", "価格表を見ましょう。"),
        (9.5, "dst", "はい。"),
        (10.5, "dst", "それから納期です。"),
    ])
    assert table == [
        ("Let's look at the price list.", "価格表を見ましょう。"),
        ("Okay.", "はい。"),
        ("Then the delivery dates.", "それから納期です。"),
    ]
    assert not any("merge_into" in o for o in ops)


def test_split_translation_appends_to_the_same_row():
    table, _ = replay([
        (1.0, "src", "I think the first batch is slow, but I don't know how we could make it any faster."),
        (2.4, "dst", "最初のバッチは遅いと思います。"),
        (3.6, "dst", "でも、どうすればもっと速くできるかはわかりません。"),
        (6.0, "src", "Let's ask the vendor."),
        (7.3, "dst", "ベンダーに聞きましょう。"),
    ])
    assert table == [
        ("I think the first batch is slow, but I don't know how we could make it any faster.",
         "最初のバッチは遅いと思います。でも、どうすればもっと速くできるかはわかりません。"),
        ("Let's ask the vendor.", "ベンダーに聞きましょう。"),
    ]


def test_split_translation_with_the_next_source_already_waiting():
    table, _ = replay([
        (1.0, "src", "I think the first batch is slow, but I don't know how we could make it any faster."),
        (2.4, "dst", "最初のバッチは遅いと思います。"),
        (3.0, "src", "Okay."),
        (3.4, "dst", "でも、どうすればもっと速くできるかはわかりません。"),
        (4.2, "dst", "はい。"),
    ])
    assert table == [
        ("I think the first batch is slow, but I don't know how we could make it any faster.",
         "最初のバッチは遅いと思います。でも、どうすればもっと速くできるかはわかりません。"),
        ("Okay.", "はい。"),
    ]


def test_ja_to_en_tag_folds():
    table, _ = replay([
        (1.0, "src", "今日は少し回線が遅いです。"),
        (1.6, "src", "ですよね。"),
        (2.7, "dst", "The connection is a bit slow today, isn't it?"),
        (4.5, "src", "資料は後でメールで送ります。"),
        (6.0, "dst", "I'll send the materials by email later."),
    ])
    assert table == [
        ("今日は少し回線が遅いです。ですよね。", "The connection is a bit slow today, isn't it?"),
        ("資料は後でメールで送ります。", "I'll send the materials by email later."),
    ]


def test_dropped_translation_does_not_shift_later_rows():
    table, _ = replay([
        (1.0, "src", "Thanks for joining today."), (2.4, "dst", "本日はご参加ありがとうございます。"),
        (4.0, "src", "We have three topics on the agenda."),  # its translation never comes
        (8.0, "src", "First, the catalog schedule."), (9.4, "dst", "まず、カタログのスケジュールです。"),
        (11.0, "src", "Second, the pricing."), (12.4, "dst", "次に、価格です。"),
    ])
    assert table == [
        ("Thanks for joining today.", "本日はご参加ありがとうございます。"),
        ("We have three topics on the agenda.", ""),
        ("First, the catalog schedule.", "まず、カタログのスケジュールです。"),
        ("Second, the pricing.", "次に、価格です。"),
    ]


def test_delayed_translation_is_not_mistaken_for_a_drop():
    table, _ = replay([
        (1.0, "src", "Thanks for joining today."), (2.4, "dst", "本日はご参加ありがとうございます。"),
        (4.0, "src", "We have three topics on the agenda."),
        (8.0, "src", "First, the catalog schedule."),
        (8.4, "dst", "議題は三つあります。"),  # late, but just after the next source
        (9.6, "dst", "まず、カタログのスケジュールです。"),
    ])
    assert table[1:] == [("We have three topics on the agenda.", "議題は三つあります。"),
                         ("First, the catalog schedule.", "まず、カタログのスケジュールです。")]


def test_translation_without_source_keeps_its_own_row():
    table, _ = replay([
        (1.0, "dst", "Good morning."),  # the source transcript never came
        (9.0, "src", "今日の議題を確認しましょう。"),
        (10.5, "dst", "Let's check today's agenda."),
    ])
    assert table == [("", "Good morning."), ("今日の議題を確認しましょう。", "Let's check today's agenda.")]


def test_translation_before_its_source_shares_the_row():
    table, _ = replay([(1.0, "dst", "Good morning."), (1.3, "src", "おはようございます。"),
                       (3.0, "src", "始めましょう。"), (4.2, "dst", "Let's begin.")])
    assert table == [("おはようございます。", "Good morning."), ("始めましょう。", "Let's begin.")]


def test_never_folds_across_utterances():
    table, ops = replay([
        (7.0, "src", "I think it's sort of slow.", 1),
        (8.6, "dst", "ちょっと遅い気がします。", 1),
        (8.0, "src", "Right?", 2),
        (10.5, "src", "I don't know how fast it can do this.", 2),
        (12.0, "dst", "どうやって速くできるかわからないけど。", 2),
    ])
    assert not any("merge_into" in o for o in ops)
    assert ("Right?", "どうやって速くできるかわからないけど。") in table  # the old pairing: nothing is moved


def test_unfinished_sentences_continue_their_row():
    table, _ = replay([
        (1.0, "src", "二つ目の"), (1.5, "src", "文です。"),
        (2.0, "dst", "The weather is nice today,"), (2.4, "dst", "isn't it?"),
    ])
    assert table == [("二つ目の文です。", "The weather is nice today, isn't it?")]


def test_rows_seal_in_order_after_quiet():
    saved = []
    p = Pairer(on_row=saved.append)
    p.src("Hello.", 1.0, 1)
    p.dst("こんにちは。", 2.0, 1)
    p.src("Can you hear me?", 3.0, 1)
    p.seal(2.0 + SEAL_S - 0.1)
    assert saved == []
    p.seal(2.0 + SEAL_S)
    assert [r.src_text for r in saved] == ["Hello."]
    p.seal(3.0 + SEAL_S)
    assert [(r.src_text, r.dst_text) for r in saved] == [("Hello.", "こんにちは。"), ("Can you hear me?", "")]


def test_helpers():
    assert units("I don't know.") == 3 and units("こんにちは。") == 2.5
    assert join_text(["Hello.", "How are you?"]) == "Hello. How are you?"
    assert join_text(["二つ目の", "文です。"]) == "二つ目の文です。"
    assert join_text(["そうです。", "OK."]) == "そうです。OK."
