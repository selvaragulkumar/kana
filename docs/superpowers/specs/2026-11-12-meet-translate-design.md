# meet-translate: two-way live voice translation for Google Meet on a Mac

Date: 2026-11-12. Owner: Rahul. Status: approved by opting out of questions ("my base is pretty clear").

## Intent

Rahul joins Google Meet calls with Japanese speakers. He speaks English and wants the
other side to hear Japanese; the other side speaks Japanese and he wants to hear English
in his earphones. Personal tool, one user, runs on his MacBook while Meet runs in Chrome.
Nothing is deployed anywhere.

## Goals

- Inbound: Meet audio (Japanese) -> English speech in Rahul's earphones, a few seconds behind.
- Outbound: Rahul's mic (English) -> Japanese speech into Meet as his microphone.
- Both directions at once, independent, each with its own Gemini Live session.
- Runs from one terminal command; survives a one-hour call (reconnects, resumes).
- Transcripts of both directions printed to the terminal so he can see what was said and
  what was sent.

## Non-goals

- No GUI, no menu-bar app, no packaging. A terminal program is the deliverable.
- No speaker separation. One inbound stream; the model's voice mirroring is what
  distinguishes speakers.
- No Teams support in this version (nothing in the design prevents it; it is only audio
  device selection in the meeting app).
- No mixing of the original voice into the translated output.

## Anti-goals

- Audio feedback loops (the counterpart hearing their own words translated back, or Rahul's
  translated Japanese echoing into his inbound stream). The device wiring must make this
  impossible, not merely unlikely.
- Sending Rahul's audio while he believes he is muted.

## Decisions (made by Claude, Rahul opted out of the questions)

| Topic | Decision | Why |
|---|---|---|
| Language | Python 3.13 in `.venv`, `google-genai`, `sounddevice`, `numpy` | Rahul's stack; SDK has `TranslationConfig` |
| Model, default | `gemini-3.5-live-translate-preview` via Gemini Developer API | only model with voice mirroring and mid-sentence streaming; not on Vertex |
| Model, fallback | `gemini-3.8-live` (GA) with a translate-only system instruction | stable; switch with `--model` |
| Auth | `GEMINI_API_KEY` in `.env`, key created under the owner's GCP project so its credits apply | Live Translate is not on Vertex, so gcloud ADC cannot be used for it |
| Virtual devices | BlackHole 2ch = Meet microphone (app writes Japanese into it); BlackHole 16ch = Meet speaker (app reads Japanese from it) | two distinct devices so the two paths cannot touch |
| Rahul's devices | real mic (MacBook / earphone mic) -> app; app -> earphones | selected by name via CLI flags, defaults = system defaults |
| Push-to-talk | terminal keypress: space toggles outbound live/muted, prints state | no Accessibility permission, no hotkey library |
| Target languages | `--out ja --in en` defaults, both BCP-47, any pair works | `translation_config.target_language_code` per session |
| Echo | `echo_target_language=False` both ways | if Rahul speaks Japanese the outbound stays silent; if the counterpart speaks English the inbound stays silent |
| Session life | `context_window_compression` + `session_resumption` + `go_away` handling, auto-reconnect with the stored handle | audio-only sessions cap at 15 min, connections at ~10 min |
| Testing | `--in-file path.wav` replaces the inbound capture; `--out-file path.wav` replaces the mic; transcripts asserted | no human needed for the first pass |

## Audio wiring (the part that must be exact)

```
                     +-------------------+
 Rahul's mic  ---->  |                   | ----> BlackHole 2ch  ----> Meet "Microphone"
 (16 kHz mono)       |   meet-translate  |       (24 kHz Japanese)
                     |                   |
 BlackHole 16ch ---> |  2 Live sessions  | ----> Earphones
 (Meet "Speakers",   |                   |       (24 kHz English)
  Japanese)          +-------------------+
```

In Meet settings: Microphone = BlackHole 2ch, Speakers = BlackHole 16ch.
In macOS: system output stays on the earphones so only the app's English reaches them.
Rule: Meet never sees the real mic; the earphones never receive the virtual-mic feed.

## Program structure

`meet_translate/` package, `python -m meet_translate` entry point.

- `audio.py`: device lookup by substring, input stream (16 kHz mono int16, 100 ms blocks)
  into an asyncio queue, output stream (24 kHz mono int16) fed from an asyncio queue with
  silence on underrun. Resampling of a device that cannot open at the needed rate is done
  in numpy (linear) so odd devices still work.
- `session.py`: one `Direction` = one Live session. Takes an input queue, an output queue,
  target language, model, a label ("IN"/"OUT"). Loop: connect (with resumption handle if
  any) -> concurrently send 100 ms chunks and receive audio/transcripts -> on `go_away`,
  error or close, reconnect with the latest handle, back off 1s/2s/4s, keep the input queue
  draining so the mic stream never blocks. Prints `[IN ja->en] <input transcript>` and
  `[IN ja->en] => <output transcript>`.
- `ptt.py`: raw-terminal key reader; space toggles a `muted` flag the outbound sender checks
  (it sends silence-free: simply does not send while muted). `q` quits.
- `__main__.py`: argparse (`--mic`, `--spk`, `--meet-mic`, `--meet-spk`, `--in`, `--out`,
  `--model`, `--in-file`, `--out-file`, `--list-devices`), wires the four streams and two
  directions, prints a startup summary with the chosen device names and cost estimate line.
- `tests/`: unit tests for device matching, resampling, PTT flag; one integration test
  marked `live` that needs `GEMINI_API_KEY`, plays a short Japanese WAV (generated by
  macOS `say -v Kyoko`) through a Direction and asserts the output transcript contains
  expected English words and that audio bytes were received.

## What the builder decides

File layout inside the package, exact backoff numbers, how transcripts are buffered before
printing, numpy vs. a library for resampling, logging format.

## Open items for Rahul (not blocking the build)

1. Run `gcloud auth login` (token expired) and create the Gemini API key in the GCP project
   (AI Studio -> Get API key -> choose that project), paste into `.env` as
   `GEMINI_API_KEY=...`.
2. Run `brew install --cask blackhole-2ch blackhole-16ch` (asks for the Mac password).
3. First live call with a Japanese speaker to judge lag and turn-taking.
