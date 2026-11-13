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

## 2026-11-13 — first real Google Meet call, app 0.1.0 (engine 50b3f12)

**Setup.** The author on a MacBook Pro (earphones, built-in microphone, kana 0.1.0 from the installed app, `--register default`) and a second participant on a phone in the same room, speaking Japanese. Meet in Chrome with microphone BlackHole 2ch and speakers BlackHole 16ch once set correctly (see below). 8 minutes, 67 outbound rows and 13 inbound rows in the saved transcript `2026-11-13-1648`.

**Result.** Both directions worked. The panel's running figure for outbound onset→audio was 1.2 s; cost $0.09 (≈¥13) at 4:14 into the call. The outbound Japanese from neutral English came out plain-polite (です・ます, e.g. "うん、でも遅延は悪くなかったと思う。" for casual English, "日本語で何か言ってもらえますか？" for a request), in the author's voice. The second participant heard it as natural Japanese. Owner's verdict: "works amazingly well".

**What went wrong, and what changed because of it.**

- Meet's microphone and speakers were left on the Mac devices at first. The phone heard raw English, and the Mac microphone heard the phone's Japanese while Talk was on, so three outbound rows carried Japanese as their source and never got a translation (typing dots stayed). Fixed: rows the model never translates settle to "—" (`untranslated` event, 10 s backstop); pass-through when idle and the Setup checklist make the device step harder to miss.
- With nothing passing the voice gate for about 4 minutes, Gemini closed the inbound session with `1008 Session closed due to client inactivity`; the reconnect showed a warning and lost a second or two. Fixed: a 100 ms zero-filled keepalive after every 20 s with nothing sent, muted or not.
- Talk is a toggle and was left on, so room sound went out between sentences. Changed: Right ⌥ hold-to-talk by default, tap to toggle.
- Same-room test artefact: the phone's microphone picked up the author's English and Meet sent it back, so several inbound rows have English sources ("Can you say something like longer in Japanese?"). In those overlapping turns the transcript pairing drifted by one row in places (a translation shown beside the following source). Open: pairing under overlapping, mixed-language turns; tracked in docs/ROADMAP.md.
