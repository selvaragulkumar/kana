# Outbound Japanese register

kana is used in business meetings, where outbound Japanese should be in business register: です・ます
throughout, with 尊敬語 and 謙譲語 where a Japanese business speaker would use them, and never タメ口
(casual speech). This page records how each model behaves. It also explains the two modes:
`--register default`, the default, keeps your own voice; `--register business`, opt-in,
guarantees keigo.

## Result in one paragraph

Live Translate mirrors the speaker's register. Casual English comes out as タメ口, such as
「うん、それでいいよ。」 and 「ちょっと待って。確認するね。」. This happened for all 4 casual inputs in all
3 runs. Live Translate accepts a `system_instruction` without an error, and the instruction does
move it toward politeness. It is not a guarantee, though: one input stayed casual every time, a
short input failed in 2 of 3 runs, and one translation was wrong in 2 of 3 runs. The general Live
model with a keigo instruction produced no casual output in 36 tries, with 31 in business keigo.
The price is that the speaker's voice is not preserved and latency rises by about 0.45 s.

## Method

- **Script:** [`tests/register_eval.py`](../tests/register_eval.py), run as
  `.venv/bin/python tests/register_eval.py --out <dir>`. It needs `GEMINI_API_KEY`, and a run of
  36 sessions costs a few cents.
- **Inputs:** 12 English utterances spoken by macOS `say -v Samantha`: 4 casual, 4 neutral and 4
  polite.
- **Path:** each utterance goes through one outbound direction, English to Japanese, using the
  engine's own session code. The audio starts 0.5 s after the session connects, so no words are
  lost. In every run the input transcript matched the spoken sentence.
- **Configurations:**

| Name | Model | Instruction |
|---|---|---|
| translate | `gemini-3.5-live-translate-preview` | none: what Live Translate users get |
| translate+instr | `gemini-3.5-live-translate-preview` | the keigo instruction, sent next to `translation_config` |
| fallback+keigo | `gemini-3.8-live` | the keigo instruction |

- **The keigo instruction** is `KEIGO_INSTRUCTION` in `kana/session.py`:
  > あなたは同時通訳者です。聞こえた発話を日本語のビジネス敬語に翻訳してください。必ずです・ます調を使い、謙譲語・尊敬語を適切に使い分けてください。タメ口や砕けた表現は禁止です。翻訳のみを出力し、説明・挨拶・返答は一切しないでください。発話がすでに日本語の場合は何も出力しないでください。
- **Repeats:** each configuration ran 3 times on 2026-11-12, giving 108 sessions. All connected on
  the first try, with no errors and no reconnects.

## Grades

The grades are strict:
- **casual:** any plain-form sentence or タメ口 marker (ねえ, うん, よ, ね, plain-form endings)
  anywhere in the output.
- **polite:** です・ます throughout, but the speaker's own actions or requests are not in 尊敬語
  or 謙譲語. For example 「確認します」 rather than 「確認いたします」, and 「もらえますか」 rather than
  「いただけますでしょうか」.
- **keigo:** です・ます throughout, with the 尊敬語 and 謙譲語 forms a business speaker would use.
- **failed:** no output, or a fragment.

Each cell shows the outputs seen across the 3 runs, with a count when they differed.

| # | English (input register) | translate | translate+instr | fallback+keigo |
|---|---|---|---|---|
| 1 | Hey, can you send me that file? (casual) | **casual** 3/3: ねえ、そのファイル送ってくれる？ | polite 3/3: あの、そのファイルを送ってもらえますか？ | keigo 3/3: そのファイルをお送りいただけますでしょうか。 |
| 2 | Yeah that works for me. (casual) | **casual** 3/3: うん、それでいいよ。 | **failed** 2/3 (no output; 「す。」), polite 1/3: 大丈夫です。 | keigo 3/3: (はい、)それで問題ございません。 |
| 3 | No way, that's way too expensive. (casual) | **casual** 3/3: ありえない／まさか。それは高すぎる。 | **casual** 3/3: とんでもない。それは高すぎます。 | polite 2/3: それはあまりにも高額すぎます。 keigo 1/3: それはあまりにも高額でございます。 |
| 4 | Gimme a sec, I'll check. (casual) | **casual** 3/3: ちょっと待って。確認するね／よ。 | polite 3/3: 少々お待ちください。確認します。 | keigo 3/3: 少々お待ちください。確認いたします。 |
| 5 | We can deliver in three weeks. (neutral) | polite 3/3: 3週間で納品できます。 | polite 3/3: 3週間で納品できます。 | polite 3/3: 3週間で納品可能です。 |
| 6 | What is your budget for this quarter? (neutral) | polite 3/3: 今四半期の予算はいくらですか？ | polite 3/3: 今四半期の予算はいくらですか？ | keigo 3/3: 今四半期のご予算はおいくらでしょうか。 |
| 7 | I think the second option is better. (neutral) | polite 3/3: 2つ目の選択肢の方がいいと思います。 | polite 3/3: 2つ目の選択肢の方が良いと思います。 | keigo 3/3: 第二案の方がより適切であると存じます。 |
| 8 | Let's schedule a follow-up next Tuesday. (neutral) | polite 3/3: 来週の火曜日にフォローアップをしましょう。 | polite 3/3: 来週の火曜日にフォローアップをしましょう。 | keigo 3/3: 来週の火曜日に、フォローアップのお打ち合わせを設定いたしましょう。 |
| 9 | Could you please share the proposal by Friday? (polite) | keigo 3/3: 提案書を金曜日までに共有していただけますか？ | keigo 3/3, but **wrong** 2/3: 金曜日のアイデアを…／金曜日の午前中までに… | keigo 3/3: 金曜日までに提案書をご共有いただけますでしょうか。 |
| 10 | Thank you very much for your time today. (polite) | keigo 3/3: 本日はお時間をいただき、ありがとうございます。 | keigo 3/3: 本日はお時間をいただき、誠にありがとうございます。 | keigo 3/3: 本日はお時間をいただき、誠にありがとうございます。 |
| 11 | I'm afraid we cannot accept those terms. (polite) | polite 3/3: 申し訳ありませんが、その条件は受けけられません。 (the stutter 「受けけ」 appeared in all 3 runs) | keigo 3/3: 申し訳ございませんが、その条件はお受けできかねます。 | keigo 3/3: 大変恐縮ではございますが、その条件をお受けすることはいたしかねます。 |
| 12 | Would it be possible to extend the deadline? (polite) | polite 3/3: 締め切りを延ばすことは可能ですか？ | polite 3/3: 締め切りを延長することは可能でしょうか？ | keigo 3/3: 期限を延長していただくことは可能でしょうか。 |

### Totals over 36 outputs per configuration

| Configuration | casual | failed | polite | keigo | Median onset to audio |
|---|---|---|---|---|---|
| translate | **12** | 0 | 18 | 6 | 2.92 s |
| translate+instr | **3** | **2** | 22 | 9 | 2.97 s |
| fallback+keigo | **0** | 0 | 5 | 31 | 3.37 s |

The latency column comes from the third run, one utterance each. It is the time from speech onset
to the first audible translated audio.

## Does Live Translate accept an instruction?

It accepts one. A `system_instruction` next to `translation_config` was neither rejected nor
ignored. All 36 sessions connected without an error, and the outputs changed consistently:

- **Items 1, 4 and 11:** 「送ってくれる？」 became 「送ってもらえますか？」, 「ちょっと待って」 became
  「少々お待ちください」, and 「申し訳ありません…受けけられません」 became 「申し訳ございません…お受けできかねます」.
  Each change held in 3 of 3 runs.
- **Casual outputs:** they fell from 12 to 3 per 36.

It is only partly honoured, so it cannot guarantee the register:

- **Item 3:** 「とんでもない。」 stayed a plain-form sentence in every run.
- **Item 2:** the short reply failed in 2 of 3 runs, giving no output or the fragment 「す。」.
- **Item 9:** the translation was wrong in 2 of 3 runs.
- **Own actions:** these stay plain polite rather than humble, for example 「確認します」.

The instruction is not a documented Live Translate feature, so its effect may change without
notice.

## Decision

**`--register default` is the default.** Live Translate runs on both directions, so your
Japanese is spoken in a voice mirrored from yours, and the register mirrors how you speak. This
was the product owner's ruling on 2026-11-12: hearing your own voice in Japanese matters more than
a guaranteed keigo register.

### How to get polite output on the default

Speak neutral or polite English. Every non-casual input in the evaluation came out polite or in
keigo: 24 of 24 outputs, the 8 neutral and polite sentences × 3 runs. Examples are
「3週間で納品できます。」, 「提案書を金曜日までに共有していただけますか？」 and
「本日はお時間をいただき、ありがとうございます。」. Only casual phrasing produced タメ口: "Hey", "Yeah",
"No way" and "Gimme a sec". Phrasing a request as "Could you…" or "Would it be possible…", and
avoiding slang, keeps the Japanese in です・ます. When the meeting needs strict keigo, switch to
`--register business`.

### `--register business` (opt-in)

Business mode moves the outbound direction to the general Live model (`gemini-3.8-live`) with the
keigo instruction whenever the outbound language is Japanese. The inbound direction stays on Live
Translate. In the evaluation it produced no casual output in 36 tries, with 31 in keigo. The
trade-offs:

- **Voice:** the outbound voice is a stock voice, not yours. Live Translate's voice preservation is
  given up for the guarantee of register.
- **Latency:** outbound latency rises by about 0.45 s at the median.
- **Freer wording:** the general model paraphrases more freely and adds courtesy. For example, it
  rendered "No way" as 「到底受け入れられません」 in one run, and "next Tuesday" as a meeting
  (お打ち合わせ). None of these changed the business meaning in this set, but it is a translator
  that edits tone, by design.
- **Cost:** the two models are billed differently, according to the server's token counts (see
  Cost in [ENGINE.md](ENGINE.md)). Live Translate costs $3.50 in and $21 out per million audio
  tokens. It bills as many output tokens as input tokens sent, and the silence it streams
  afterwards is not billed. The general model costs $3.00 in and $12 out per million. It bills
  output only for the speech it returns: 103 tokens, about 4.1 s, in one measured turn, which cost
  $0.0021 in audio. It also bills text input for the instruction and context on every turn: 390
  tokens in that turn. That text is not in the usage event's `usd`, but the event shows it as
  `in_text_tokens`.
- **The `ready` event** carries `"register"`, `"in_model"` and `"out_model"`, so the app can show
  which model speaks for you.

When the outbound language is not Japanese, business mode leaves the outbound direction on Live
Translate, because the instruction is written for Japanese. If `--model` names a general model
already, both directions use it, and the outbound direction gets the keigo instruction.

## Re-running

```
.venv/bin/python tests/register_eval.py --out /tmp/register-eval
.venv/bin/python tests/register_eval.py --out /tmp/register-eval --configs fallback+keigo
```

The script writes `results.json`, holding the Japanese, the heard English, the returned audio
seconds and the latency per utterance. It also writes `table.md` with a heuristic pre-grade. The
pre-grade is a reading aid; the grades above are a human reading.
