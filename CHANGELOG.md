# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Credit line.** "a product of zag" with the ZAG wordmark under the panel footer and at the end of Setup, in English and Japanese; click opens withzag.com. Trademark note in docs/BRAND.md and the READMEs.

## [0.1.0] - 2026-11-13

First public release. Built and used on the author's Mac (Apple silicon); the first real Google Meet call is logged in docs/VERIFICATION.md. Not notarised: see the Gatekeeper steps in the README.

### Added

- **Japanese UI.** The whole app (panel, mini bar, captions hint, ••• and menu-bar menus, Setup, tooltips, error headings and the app's own error messages) is available in Japanese. It follows the macOS language (Japanese when the first preferred language is Japanese) and ••• › Language overrides it with System / English / 日本語, applied live. Strings live in `app/Resources/{en,ja}.lproj/Kana.strings` behind a small `L10n` helper; `app/check_l10n.sh` checks that every string has both languages. The microphone prompt is translated too. Engine messages, product and device names stay in English. Offscreen renders take `--lang ja`.

- **OpenAI as a second engine (opt-in).** `--provider openai` (or `--model gpt-realtime-translate`) runs both directions on OpenAI's realtime translation model over its websocket, with the same voice gate, transcripts, pairing, latency events and playback. It needs `OPENAI_API_KEY` (a missing key is one fatal error); `--env-file` reads keys from another `.env`. Cost is priced at $0.034 per minute of audio sent and marked `est: true` on `usage` and `audio` events, because the endpoint reports no usage. No register control: `--register business` is refused on it. Gemini stays the default and is unchanged.
- `tools/latency_bench.py --provider openai` measures it on the same clips.
- App: ••• › Engine (Gemini / OpenAI), persisted; an optional OpenAI key card in Setup, stored in the login Keychain (account `OPENAI_API_KEY`); Business keigo is disabled while OpenAI is chosen, and the cost shows "est.".
- **Pass-through when idle.** While the app is open but not live, `--passthrough` copies BlackHole 16ch to your earphones and your microphone to BlackHole 2ch, untranslated, at the devices' native rate (no key, no network), so Meet works as a normal call between sessions. Start swaps in the interpreter, Stop swaps it back. The pill reads "Passing through" and the talk bar "Meet hears your mic directly · mute in Meet": the microphone is not gated by talk there. It refuses a BlackHole earphone and never writes to BlackHole 16ch. `ready` carries `mode: "passthrough"`. Toggle: ••• › Pass audio through when idle (on by default).
- **Talk key: hold Right ⌥ to talk, tap to toggle.** The default talk key is Right ⌥ (hold = push-to-talk, a tap under 350 ms latches, a second tap stops). ••• › Talk key and Setup › Permissions offer Right ⌘, Fn/🌐 and the old ⌃⌥Space. The pill and tooltips show the chosen key.
- **Mini bar Start/Stop.** Clicking the mark in the minimized bar starts a session with the saved devices and languages, or stops it; the mark breathes while live (opacity only under Reduce Motion).

- **Windows groundwork in the engine (not yet run on Windows).** A per-platform data folder (`%LOCALAPPDATA%\kana` on Windows), `--host-api` (WASAPI on Windows by default, no filter on macOS), VB-Audio cable names (`CABLE-A`/`CABLE-B` defaults on Windows, either end of a cable, MME's 31-character names), cable-aware pass-through checks, UTF-8 stdio and console push-to-talk on Windows. macOS behaviour is unchanged. Audit and design: `docs/research/windows.md`, `docs/superpowers/specs/2026-11-13-windows-design.md`.

Engine (`python -m kana`):

- **Two directions at once.** Inbound: meeting audio from BlackHole 16ch is interpreted and spoken into your earphones. Outbound: your microphone is interpreted and spoken into BlackHole 2ch, which the meeting app uses as its microphone. Each direction runs its own Gemini Live session.
- **Default model** `gemini-3.5-live-translate-preview` (Gemini Live Translate, voice-preserving speech-to-speech), with `--model gemini-3.8-live` as a stable fallback driven by a translate-only system instruction.
- **Register control.** `--register default` keeps Live Translate in both directions, with your voice and your register. `--register business` moves outbound Japanese to `gemini-3.8-live` with a keigo instruction, which guarantees です・ます and keigo in a stock voice. The evaluation is in `docs/REGISTER.md`.
- **Any language pair** through `--in` and `--out` (BCP-47 codes). Defaults: you hear English, the meeting hears Japanese. Same-language speech is not echoed.
- **Push-to-talk.** Outbound starts muted. Space toggles it in the terminal.
- **Long calls.** Session resumption handles, context window compression, `go_away` handling and reconnect with 1 s / 2 s / 4 s backoff keep each direction alive past the per-connection and per-session limits.
- **Voice-activity gating** (`--vad auto`, the default) in both directions: an energy gate with a learnt noise floor, 300 ms pre-roll and a measured 2 s hangover. Silence is not sent and not billed. `--vad off`, `--vad-threshold` and `--vad-hangover` tune it.
- **Cost from the API's own counts.** A `usage` event reports the audio and text tokens Google counted for each direction and their price. The per-second `audio` event carries the running cost.
- **Latency readout.** A `latency` event per utterance (speech onset to first audible translated audio, and source to translated transcript), and the running median in each `audio` event.
- **Saved transcripts.** Each run writes a Markdown table and an SRT file to `~/Library/Application Support/kana/transcripts/`. `--no-save` and `--save-dir` control it.
- **JSON-lines protocol** (`--json`): events on stdout (`ready`, `saved`, `talk`, `session`, `transcript`, `latency`, `audio`, `usage`, `error`, `bye`), commands on stdin (`talk`, `quit`), and `--list-devices --json`. The `ready` event names the register and the model each direction uses. The reference is `docs/ENGINE.md`.
- **Loop guard.** The engine refuses to start when both directions would capture the same device or when the earphones and the meeting microphone are the same device.
- **Test seams.** `--in-file` / `--out-file` WAV injection (playback starts once the session connects), `--dump-in` / `--dump-out`, `--only in|out`, unit tests including a reconnect chaos test, a register evaluation script, and one opt-in live test.

App (`kana.app`, SwiftUI, macOS 14+):

- **Menu-bar panel** with Start/Stop, a Talk toggle, ⌃⌥Space from any app, mic and earphone pickers, a live two-column transcript and per-direction session state. Engine errors are shown, never swallowed.
- **Language cards** ("You hear …", "Meet hears …") with a swap button and presets pairing English with Japanese, Chinese, Korean, Spanish, French, German, Hindi or Tamil, plus a custom BCP-47 pair.
- **Business keigo switch** under the language cards when the meeting hears Japanese. It passes `--register business`; off by default. The stock-voice trade-off is in its tooltip.
- **Floating captions**, off by default. A small click-through strip at the bottom of the screen with the newest inbound line and the one before it, above other apps.
- **Hidden from screen sharing** by default. The panel and the caption strip stay out of shares, recordings and screenshots unless you turn on "Visible in screen share".
- **Setup doctor** (••• › Setup…, and automatically after a start fails with a device or key error). Checks both BlackHole devices, microphone and Accessibility access, the key and the meeting settings, shows the install line, and plays a test tone through each BlackHole device to confirm it is wired.
- **API key in the Keychain.** The key is stored in the login Keychain and passed to the engine in its environment, never on the command line. A `.env` file still works as a fallback.
- **Latency badge and cost meter** in the footer: median delay for each direction, running cost in USD and approximate yen from the engine's token-based figure, and the silence the voice gate skipped.
- **Transcripts menu.** A "Save transcripts" toggle, "Open Last Transcript" and "Transcripts Folder".
- **Fake engine** (`app/fake_engine.py`) for testing the app without audio, a key or a network.
- Built with `app/build.sh` and the Command Line Tools only.

- **One-shot install.** `app/release.sh` builds a DMG with the Python engine bundled inside `kana.app` (`app/bundle_engine.sh`, a pinned relocatable Python 3.13), so no Homebrew, Python or terminal is needed. First launch runs a Setup flow: one click downloads and installs both BlackHole drivers with a single administrator prompt (installer SHA-256 and signer checked), then the Gemini key, then microphone and Accessibility access. `kana --driver-install-dry-run` prints the admin command without installing.
- **Playback catch-up** (`--catch-up on`, the default). While playback is behind the model, its streamed silence is skipped, so the first translated audio arrives sooner: median speech onset to audio 1954 → 1632 ms (en→ja) and 2360 → 1961 ms (ja→en) in the benchmark. `tools/latency_bench.py` and `docs/LATENCY.md` hold the method, every candidate tried and the numbers.
- **Faster meeting capture** (`--capture-latency low`, the default). The BlackHole 16ch input opens at PortAudio latency `low` with 10 ms blocks, collected into 100 ms chunks, so each chunk of meeting audio reaches the model about 60 ms sooner (67 → 7 ms after its last sample, measured on the BlackHole loopback with `tools/capture_latency.py`). Microphones keep the defaults. `--capture-latency default` restores the old capture.
- **`--backend developer|vertex`** (default `developer`). `vertex` runs the same Live Translate sessions on Vertex AI at location `global` with Google Cloud application-default credentials and `--gcp-project`; `ready` reports the models with an `@vertex` suffix. Measured against the Developer API in `docs/LATENCY.md`.
- **Transcript rows paired by timing**, not order, so a short tag the model folds into the previous sentence no longer shifts every later row.
- **App polish.** Opening animation from the design handoff (brackets trace in, once per launch), eased connecting spin, flicker-free minimize and expand, panel stays open until ×, launching kana again opens the panel, and builds sign with a stable local identity so macOS keeps the Accessibility grant across rebuilds.

### Changed

- **The panel's × quits kana**, stopping a live session or pass-through cleanly first (the same path as ••• › Quit kana). Reopen kana from Applications or Spotlight.

- Renamed from meet-translate to kana. The Python package is now `kana` (`python -m kana`, console script `kana`), and the app is `kana.app` with the bundle id `com.selvaragulkumar.kana`.


### Fixed

- **An idle direction no longer gets closed by the server.** With the voice gate closed nothing was sent, and after about 4 minutes of a silent meeting Gemini closed the inbound session ("1008 Session closed due to client inactivity"); the reconnect lost a second or two of speech and showed a warning. While a session is up, muted or not, the engine now sends 100 ms of zero-filled silence after every 20 s with nothing sent (never microphone audio while muted) (about 0.5 % of the gated audio, billed and counted in `sent_s`). It never counts as speech.
- **Rows the model never translates no longer show typing dots forever.** When an utterance closes after 1.5 s of quiet with a row whose source is final and no translation, the engine sends a new `untranslated` event (`dir`, `row`), and the app shows a quiet grey "—" (tooltip "No translation") in place of the dots. This happened when the other person's Japanese reached the microphone on the outbound direction. As a backstop, the app settles a row the same way 10 s after its source was last updated once a newer row exists in that direction. A late translation still fills the row.

[Unreleased]: https://github.com/selvaragulkumar/kana/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/selvaragulkumar/kana/releases/tag/v0.1.0
