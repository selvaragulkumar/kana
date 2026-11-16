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

## 2026-11-16 — second real call: Zoom, 85 minutes, customer meeting (app 0.1.1, engine pairing v1)

**Setup.** The author on a MacBook Pro with earphones, kana 0.1.1 from the installed app, `--register default`, Zoom in the browser with Speaker = BlackHole 16ch and Microphone = BlackHole 2ch (after a swapped start, below). Three remote participants speaking Japanese; a Japanese-speaking colleague beside the author on the same Zoom line. An independent transcript of the meeting from the colleague's notetaker served as the reference for accuracy. The meeting content is confidential; only aggregate numbers are recorded here.

**Result.** Inbound interpretation ran for 85 minutes with about 1 s delay and clear audio; the author's verdict was "better than what I used before". 819 inbound rows. Cost from the panel at Stop about ¥450, i.e. ¥5.3 per minute (¥320 per hour) for dense, near-continuous speech, against ¥3.1 per minute in the sparser first call.

**Accuracy, scored against the reference** (157 substantive passages, meaning preservation 0–3): mean 1.90, or 2.01 excluding the two capture gaps; distribution 0/1/2/3 = 11/42/56/48. Numbers and prices right 61 of 77, proper and product names 30 of 48, questions kept as questions 31 of 41, passages with no English 11 (9 from the gaps), invented English 6 short fragments. Of the low scores, 24 were audio mishearings visible in the source column (one counter word misheard about eight times, names), 14 were translation errors with a correct source (7 negation flips, 2 hundred-fold errors on 万/億, 4 inversions), 4 were two speakers merged into one sentence.

**What went wrong, and what changed because of it.**

- Zoom's two devices were set the wrong way round for the first 3.5 minutes, so the room's Japanese reached the microphone path and was shown untranslated (18 outbound rows). Roadmap: detect the target language on the microphone path at start and warn.
- The transcript panel paired the wrong Japanese with the English in most rows: 337 of 819 inbound rows English-only, about a third of the rest mismatched. Measured cause (docs/research/transcription-timing.md): Live Translate streams both transcriptions about once a second, 1:1, with no turn signals; the engine's own sentence buffer held run-on Japanese for up to minutes before pairing. Changed: pairing v2 feeds chunks as they arrive (docs/superpowers/specs/2026-11-16-pairing-v2.md); on three synthetic recordings every English row now has its own Japanese (v1: 26 of 54 anchors right).
- The engine stopped at 10:57:54 when Zoom briefly dropped and reconnected; the last minutes went untranslated and the reason was not recorded. Changed: a per-call events log beside the transcript (docs/ENGINE.md, "Events log"). In progress: reopen audio streams instead of exiting.
- English spoken in the room came back in English for about two minutes. In progress: do not play inbound audio that is already the listener's language.
- The inbound voice is chosen per model turn; with gaps mostly under 5 s it stayed on one voice across speakers and re-locked once mid-turn. Open: fixed voice option.
- 239 of 819 rows were bare acknowledgements ("Yes.", "That's right."); 27 rows were split-off sentence tails. Open: merge tails, collapse back-channel runs.
