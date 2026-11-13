# kana for Windows (2026-11-13)

Status: proposed. After the first real Meet call on macOS the owner asked for "the same one for
Windows too". This spec is built on the audit in
[docs/research/windows.md](../../research/windows.md); read that first for the reasons behind
each choice. Nothing in this spec has been run on Windows yet.

## Intent

The same interpreter on Windows 10 (2004 or later) and Windows 11, x64: Google Meet in Chrome or
Edge, your voice out in Japanese, the meeting in English in your earphones, push-to-talk, a
floating panel, saved transcripts. Same engine, same protocol, a new app shell.

## Decisions

| Topic | Decision |
|---|---|
| Engine | The existing `kana` package, unchanged in behaviour. Windows groundwork is already in (this branch): `kana/paths.py`, WASAPI selection (`--host-api`, default `auto`), VB-Audio name matching, cable-aware loop checks, UTF-8 stdio, console push-to-talk via `msvcrt`. |
| Protocol | [ENGINE.md](../../ENGINE.md) JSON lines, unchanged. Any later addition (for example a cable self-test) follows the four-places rule in AGENTS.md. |
| App stack | **Tauri 2**: Rust shell, UI in HTML/CSS/TypeScript in WebView2, the engine as a sidecar process. |
| Virtual cables | **VB-Audio VB-CABLE A+B**, installed by the user. CABLE-A carries kana's translation to Meet's microphone; CABLE-B carries Meet's speaker to kana. Any two other cables can be picked in Setup. |
| Engine runtime | python-build-standalone CPython 3.13 for `x86_64-pc-windows-msvc`, assembled on the Mac (Windows wheels via `pip --platform win_amd64`), shipped as a folder next to the app. |
| Installer | Zip for testers (M1, M2); Tauri's NSIS installer, per user, no admin (M3). Unsigned: SmartScreen warns once. |
| Key storage | Windows Credential Manager, one generic credential per key (`kana/GEMINI_API_KEY`, `kana/OPENAI_API_KEY`), through the `keyring` crate. Passed to the engine in its environment, never as an argument. |
| Talk key | Default **Right Ctrl**, hold to talk, tap to toggle (the same `TalkKeyLogic` rules: 350 ms). Right Alt offered, with the AltGr and menu-activation caveats handled in the hook. |
| Data folder | `%LOCALAPPDATA%\kana`: `engine_path`, transcripts. |

## What is identical to macOS

- The engine, its flags, the JSON protocol, the voice gate, pairing, latency events, cost, saved
  transcripts (Markdown and SRT), the reconnect and keepalive behaviour.
- The routing and its loop-proof argument: two cables, one writer and one reader each
  ([ARCHITECTURE.md](../../ARCHITECTURE.md#why-the-routing-cannot-loop)); pass-through as the idle
  state, refusing a cable as earphones.
- The panel's content: the talk bar, the two-column live transcript, devices and languages, the
  cost and latency footer, the mini bar with Start/Stop, the caption strip.
- The privacy line: no telemetry, and the engine talks only to the provider's API. The Windows
  app makes no network call of its own at all: it opens VB-Audio's page in the browser instead of
  downloading a driver (see Setup).

## What differs

| | macOS | Windows |
|---|---|---|
| Drivers | Setup downloads and installs both BlackHole drivers with one password prompt | Setup explains and links: donate for VB-CABLE A+B on VB-Audio's shop, run its installer as administrator, reboot. Setup then detects the cables. The app downloads nothing. |
| Permissions | Microphone (TCC prompt), Accessibility (talk key) | Microphone privacy switch for desktop apps (Settings); no permission for the keyboard hook |
| Extra checks | none | Communications ducking set to "Do nothing"; "Listen to this device" off on both cables; the system default output is not a cable |
| Talk key default | Right ⌥ | Right Ctrl |
| Where it lives | menu bar | notification area (tray); Windows 11 hides new icons until pinned |
| Hidden from screen share | `sharingType = .none` | `WDA_EXCLUDEFROMCAPTURE` (Windows 10 2004+) |
| First open | Gatekeeper steps | SmartScreen "More info › Run anyway" |
| Audio self-test | the app plays a tone into each cable and listens | the Tauri app has no audio code; the test moves into the engine (M3, a protocol addition) |

## Setup flow (Windows)

Same page structure as macOS, each row a check with one action:

1. **Audio cables.** Looks for "CABLE-A" and "CABLE-B" in `--list-devices --json`. Missing: text
   "kana needs two virtual audio cables. VB-CABLE A+B by VB-Audio is donationware: donate any
   amount on VB-Audio's site, download the pack from the link they send, run
   VBCable_AB_PackSetup.exe as administrator, then restart Windows." Button: **Open VB-Audio**
   (opens `https://vb-audio.com/Cable/` in the browser). Button: **Check again**. Link: "Use other
   cables" opens the two cable pickers.
2. **API key.** Same as macOS; stored in Credential Manager.
3. **Microphone access.** Reads the desktop-apps microphone consent; button opens
   `ms-settings:privacy-microphone`.
4. **Windows sound settings.** Communications ducking "Do nothing", Listen off on both cables,
   default output is not a cable. Button opens `mmsys.cpl` on the right tab. Checks that cannot
   be read reliably are shown as a checklist, not a green tick.
5. **Talk key.** Picker (Right Ctrl, Right Alt, a key combination) and a "press it now" test.
6. **Meet settings.** The checklist: Microphone "CABLE-A Output (VB-Audio Cable A)", Speakers
   "CABLE-B Input (VB-Audio Cable B)".
7. **Audio test** (M3). The engine plays a tone into each cable and listens for it.

## Install story

- M1: no installer. `git clone`, `py -3.13 -m venv .venv`, `.venv\Scripts\pip install -e .`,
  `.venv\Scripts\python -m kana`. The README gets a short "Windows (preview)" block.
- M2: `kana-windows-<version>.zip` with `kana.exe` and an `engine\` folder. Unzip anywhere, run.
- M3: `kana-setup-<version>.exe` (NSIS, per user, `%LOCALAPPDATA%\Programs\kana`, Start menu
  entry, uninstaller; WebView2 bootstrapper for Windows 10). `checksums.txt` alongside, as for the
  DMG. The VB-Audio driver is never inside.

## App structure (Tauri 2)

- `win/` at the repo root (name to settle at M2): `src-tauri/` (Rust) and `ui/` (TypeScript).
- Rust: `engine.rs` (spawn `python.exe -m kana --json …` with `CREATE_NO_WINDOW`, read lines,
  write commands, keep the last stderr KB, same lookup order as `EngineLocation`: a chosen
  checkout, the bundled engine, none); `talkkey.rs` (low-level hook thread, hold/tap logic ported
  from `TalkKeyLogic.swift` with the same tests); `window.rs` (top-most, no-activate,
  tool-window, exclude-from-capture); `secrets.rs` (Credential Manager). Events go to the UI as
  Tauri events with the engine's JSON unchanged.
- UI: the panel, the mini bar and the caption strip as three windows, rendering the same events
  the Swift views render. A fake engine run (`app/fake_engine.py`) drives it in development.

## Milestones

**M1: the engine runs on Windows from a terminal.** The Azure VM (or a PC) with VB-CABLE A+B.
`python -m kana --list-devices` shows WASAPI devices once; the round-trip test (two engines, WAV
in, WAV out, both cables) passes; a real Meet call in which the VM's Chrome uses CABLE-A and
CABLE-B and the owner joins from the Mac; terminal push-to-talk works; `--passthrough` works with
an RDP "Remote Audio" endpoint as earphones. `tools/latency_bench.py` numbers recorded in
LATENCY.md under a Windows heading. Engine fixes found here land with tests.

**M2: tray app with panel, mini bar and talk key.** Tauri 2 app, zip build. Start/Stop,
pass-through when idle, live transcript, device and language pickers, cost and latency, talk key
hold/tap, mini bar, caption strip, exclude-from-capture, key in Credential Manager. Fake engine
for UI work on the Mac where possible; behaviour checks on Windows.

**M3: installer and Setup driver step.** NSIS installer with the bundled engine; the Setup page
above, including the engine-side cable self-test (protocol addition, four places); SmartScreen
first-open steps written down; a fresh-machine test like [FRESH_MAC_TEST.md](../../FRESH_MAC_TEST.md).

**M4: docs and release.** README and README.ja.md "Windows" sections (requirements, install,
wiring, limitations), THIRD_PARTY_NOTICES for Tauri, WebView2 and the Python runtime, a release
checklist for Windows, the release on GitHub next to the DMG.

## Must be verified on a real Windows machine before any claim

Copied from the audit; none of these may be stated in the README until seen working.

1. WASAPI capture of a VB-Audio cable at `latency="low"` with 10 ms blocks, and the chunk delay
   compared with BlackHole's 7 ms; VB-CABLE's internal buffer.
2. A mono PortAudio stream on a stereo VB-CABLE endpoint in shared mode.
3. Communications ducking of kana's playback when Meet opens its microphone.
4. `WDA_EXCLUDEFROMCAPTURE` on all three windows during a Meet screen share (Chrome and Edge).
5. The talk-key hook on US, JIS and an AltGr layout, without Chrome menu activation, and with an
   elevated window in focus.
6. No-activate windows with WebView2: clicking the panel does not take focus from Meet.
7. Console push-to-talk (`msvcrt`) in Windows Terminal and the classic console.
8. UTF-8 JSON over the pipe with Japanese device names and transcripts.
9. VB-CABLE A+B install on Windows 11 with Secure Boot, and the exact endpoint names.
10. SmartScreen and Defender on the unsigned installer and the bundled `python.exe`.
11. The engine's error when the microphone privacy switch is off.
12. Building the NSIS installer from the Mac, or the build moves to Windows.
13. Bluetooth headsets: quality and latency when the headset mic is open.

## Out of scope

Arm64 Windows builds, Linux, code signing, MSIX, Microsoft Store, auto-update, a kana-owned
virtual audio driver, WASAPI process loopback (a later spike: it could remove the need for the
second cable).
