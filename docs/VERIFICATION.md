# Verification log

Append-only. Each entry is a real run against the live Gemini API, with the commit it ran on.

## 2026-11-12 — engine 7ef3fad, app 50789b3

**Local gate**

- `pytest`: 53 passed (includes the live test).
- Clean `app/build.sh --install` from an empty `app/.build`: build 35 s, no warnings, `/Applications/kana.app` installed, icon present.
- `git grep` for the old project names outside `design/` and the day's specs: only the app's alias list and the fake engine's strings remained; removed in the follow-up commit.

**Two directions at once, real API, `--register default`** (own voice both ways)

Command: `python -m kana --json --in-file ja16.wav --out-file en.wav --spk "MacBook Pro Speakers" --meet-mic "BlackHole 2ch" --no-save`, stdin held open 40 s. Inputs: a Kyoko-voiced Japanese clip and a Samantha-voiced English clip, both 16 kHz mono.

| Direction | Heard | Spoken by the model | onset→audio | src final→dst final |
|---|---|---|---|---|
| in (ja→en) | 本日はご参加いただきありがとうございます。来週の予定から始めましょう。 | Thank you for joining us today. Next week's schedule, let's start with that. | 3,007 ms | 249 ms |
| out (en→ja) | Hello. Thank you for joining today. Let's start with the schedule for next week. | こんにちは。今日はご参加いただきありがとうございます。来週のスケジュールから始めましょう。 | 2,854 ms | 1,292 ms |

Both sessions connected within 0.1 s of each other, the outbound Japanese came out polite (です・ます) from neutral English, usage events priced at Live Translate rates reached $0.0043 (in) and $0.0037 (out) for the clips, and `bye` followed the stdin EOF with both sessions closed. BlackHole 16ch was not installed on this Mac, so the Meet-speaker capture was replaced by the WAV source; the first live Google Meet call is still to come.

**App (fake engine and real engine)**, by the app implementer, screenshots in the blog set: panel idle, panel live with the real transcript above, six mark states, menu bar idle and talking, caption strip, setup. Screen-share hiding proven with a ScreenCaptureKit capture.
