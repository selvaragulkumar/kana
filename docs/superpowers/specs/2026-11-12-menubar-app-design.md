# meet-translate menu-bar app

Date: 2026-11-12. Status: approved ("go ahead"). Extends 2026-11-12-meet-translate-design.md.

## Intent

Replace the terminal command with a native macOS menu-bar app. The Python engine stays the
engine; the app launches it as a child process and talks to it over JSON lines.

## Goals

- A real `MeetTranslate.app` in `/Applications`: double-click, no terminal.
- Menu-bar icon shows state at a glance: idle (grey), running (accent), transmitting (red dot).
- One panel: Start/Stop, Talk toggle, mic and earphone pickers, live two-column transcript
  (Japanese left, English right, newest at the bottom), cost meter (minutes, estimated USD and JPY).
- Global hotkey ⌃⌥Space toggles Talk from any app (Meet in front). One Accessibility grant.
- Engine errors and reconnects visible in the panel, never silent.

## Non-goals

- No porting of audio or Live API code to Swift. No App Store, no notarisation, no sandbox.
- No settings beyond the two device pickers and language pair (ja/en swapped by a button).
- No Xcode project. Swift Package Manager + a bundling script, built from the command line.

## Engine protocol (Python side, `--json` flag)

Engine: `.venv/bin/python -m meet_translate --json [existing flags]`. With `--json`:
- stdout is JSON lines only (no banner, no transcripts as plain text). Line-buffered.
- stdin accepts JSON lines: `{"cmd":"talk","on":true|false}`, `{"cmd":"quit"}`. The raw-terminal
  PTT key reader is NOT attached in JSON mode.
- `--list-devices --json` prints one line `{"inputs":[{"index":3,"name":"MacBook Pro Microphone"}],
  "outputs":[...]}` and exits.

Events (one object per line, all have `"t"`: unix seconds float, `"ev"`):
- `{"ev":"ready","in":{"src":"BlackHole 16ch","sink":"AirPods"},"out":{"src":"MacBook Pro Microphone","sink":"BlackHole 2ch"},"model":"...","in_lang":"en","out_lang":"ja"}` after devices open.
- `{"ev":"talk","on":false}` whenever the mute state changes (also once at start).
- `{"ev":"transcript","dir":"in"|"out","kind":"src"|"dst","text":"...","final":true}` — `src` is what was heard, `dst` what was spoken by the model; emitted per flushed sentence (same flush rules as today), so `final` is always true for now.
- `{"ev":"session","dir":"in"|"out","state":"connected"|"reconnecting"|"closed","detail":"go_away"|"error: ..."|""}`.
- `{"ev":"audio","dir":"in"|"out","sent_s":12.3,"recv_s":9.8}` once per second: cumulative seconds of audio sent to and received from the model per direction (cost basis).
- `{"ev":"error","fatal":true|false,"text":"..."}`; fatal means the engine is exiting (exit code 2).
- `{"ev":"bye"}` just before a clean exit.

Cost: $3.50/1M input tokens, $21/1M output tokens, 25 tokens per audio second
→ input $0.0000875/s, output $0.000525/s. JPY at a constant 150 (shown as "approx.").

## App (Swift side, `app/`)

- Swift Package `app/Package.swift`, executable target `MeetTranslate`, macOS 14+, SwiftUI +
  AppKit. `LSUIElement = true` (no Dock icon). `MenuBarExtra` with `.window` style.
- `app/build.sh`: `swift build -c release`, assembles `build/MeetTranslate.app` (Contents/MacOS
  binary, Info.plist with CFBundleIdentifier `co.pioneerwork.meettranslate`, LSUIElement,
  NSMicrophoneUsageDescription, an app icon from `app/icon.png` if present via `iconutil`),
  ad-hoc codesign, and `--install` copies to `/Applications`.
- Engine location: defaults to the repo root resolved from `~/Library/Application Support/
  MeetTranslate/engine_path` if present, else the repo checkout (later replaced by a Setup folder picker). The app
  runs `<root>/.venv/bin/python -m meet_translate --json ...` with `cwd=<root>`.
- `EngineProcess` (ObservableObject): launch, read stdout lines, parse events, write commands,
  terminate on Stop/quit, relaunch on fatal error only when the user presses Start again.
- Panel layout (width ~380 pt):
  1. Header row: status dot + "Idle / Listening / Talking", Start/Stop button.
  2. Talk: large toggle button (full width), shows hotkey hint "⌃⌥Space". Disabled when stopped.
  3. Devices: two pickers (Mic, Earphones) populated from `--list-devices --json`; Meet devices
     fixed as BlackHole 2ch/16ch and shown as a one-line note. A ⇄ button swaps the language pair.
  4. Transcript: scrolling list, each row = one utterance: left column source text, right column
     translation, direction glyph (↓ inbound, ↑ outbound). Auto-scrolls to bottom. Keep last 200.
  5. Footer: minutes, "$0.12 · ≈¥18", session states for IN/OUT as two tiny labels, Quit.
- Global hotkey: `NSEvent.addGlobalMonitorForEvents(matching: .keyDown)` + local monitor for
  ⌃⌥Space → send talk toggle. If Accessibility is not granted, the panel shows a one-line hint
  with a button that opens System Settings › Privacy › Accessibility.
- Look: native. System font, SF Symbols (`waveform`, `mic.fill`, `mic.slash.fill`), `.regularMaterial`
  panel background, 8-pt grid, no custom colours beyond the system accent and `.red` for
  transmitting. Dark and light both correct by using semantic colours only.
- Persist: chosen devices and language pair in `UserDefaults`.

## Done means

- `app/build.sh --install` produces `/Applications/MeetTranslate.app` that launches, shows the
  icon, lists devices, starts the engine, shows transcripts from an `--in-file` dry run, and the
  Talk button and hotkey flip the engine's `talk` event.
- Engine unit tests cover the JSON event encoding and the stdin command loop.
