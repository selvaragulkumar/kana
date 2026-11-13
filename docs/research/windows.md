# kana on Windows: portability audit (2026-11-13)

The question: what does it take to run kana on Windows 10/11 with Google Meet in Chrome or Edge, the way it runs on macOS today? This page goes area by area and sorts every finding into three buckets:

- **Works unchanged**: the code or the design carries over as it is.
- **Needs a change**: known work, sized below.
- **Unverified**: cannot be settled without a real Windows machine. These are collected again at the end and in the design spec ([2026-11-13-windows-design.md](../superpowers/specs/2026-11-13-windows-design.md)).

No Windows machine was used for this audit. Facts about third-party software come from vendor pages and documentation read on 2026-11-13 (sources at the end); facts about kana come from the code at `4b6682c`.

## Summary

| Area | Verdict |
|---|---|
| Engine (Python, asyncio, Live sessions, VAD, pairing, transcripts, JSON protocol) | Works unchanged. Pure Python plus wheels that exist for `win_amd64`. |
| Audio I/O (sounddevice / PortAudio) | Works with three changes, made in this branch: pick WASAPI explicitly, match VB-Audio names, recognise VB-Audio cables in the loop checks. Latency unverified. |
| Virtual cables | VB-Audio **VB-CABLE A+B** (donationware, installed by hand). No free cable can be downloaded and installed by the app the way BlackHole is. |
| Paths, settings, console | Small changes, made in this branch: `%LOCALAPPDATA%\kana`, UTF-8 stdio, terminal push-to-talk without `termios`. |
| The app | A new app. Recommended: **Tauri 2** (Rust shell + web UI), engine as a sidecar process speaking the same JSON lines. |
| Packaging | python-build-standalone for Windows, assembled on the Mac like `app/bundle_engine.sh`; NSIS installer from Tauri; unsigned, so SmartScreen warns once. |
| Testing | An Azure Windows VM for M1 to M3 (about $15 a month kept deallocated), a real Windows PC before any release claim. |

## 1. Audio

### 1.1 sounddevice and PortAudio on Windows

**Works unchanged.** `sounddevice` ships PortAudio inside its Windows wheel (`py3-none-win_amd64`, DLLs in `_sounddevice_data`), so nothing is compiled or installed separately. `numpy` has `cp313-win_amd64` wheels. `kana/audio.py` only uses `InputStream`, `OutputStream`, `query_devices`, `check_input_settings`/`check_output_settings`, and callbacks that never block; all of that is the same API on Windows.

**Needs a change (done in this branch): the host API.** On macOS PortAudio has one host API (Core Audio) and every device appears once. On Windows the same endpoint appears once per host API, in this order:

| Host API | What it is | Latency | Notes |
|---|---|---|---|
| MME | the oldest API, WinMM | PortAudio's "low" is about 90 ms | **PortAudio's default host API.** Names cut to 31 characters. Resamples for you. |
| Windows DirectSound | emulated on top of WASAPI since Vista | about 50 to 100 ms | No advantage over WASAPI. |
| Windows WASAPI | the native audio stack since Vista | the device period, typically 10 ms in shared mode (3 ms minimum on some drivers) | Full names. Shared mode needs the endpoint's mix format (see below). |
| Windows WDM-KS | kernel streaming, bypasses the mixer | lowest | Takes the device exclusively, unstable with virtual drivers. Not for kana. |

`find_device` returned the first substring match, which on Windows is the MME entry, and a default device (`None`) is MME's "Microsoft Sound Mapper". `latency="low"` with 10 ms blocks on MME would ask for about 90 ms of buffering, undoing the capture work measured in [LATENCY.md](../LATENCY.md). So WASAPI has to be selected explicitly. The engine now does that (`--host-api`, default `auto` = WASAPI on Windows, no filter elsewhere, so macOS is unchanged): device names are matched among WASAPI devices only, `None` means WASAPI's default device, and `--list-devices --json` lists WASAPI devices only, so the app's pickers show each endpoint once. `--host-api mme` or `directsound` is the escape hatch if WASAPI misbehaves on some machine; `--host-api all` restores the old behaviour.

**Shared, not exclusive.** WASAPI exclusive mode (`sd.WasapiSettings(exclusive=True)`) locks the endpoint for one process. Chrome must be able to open the other end of each cable, and the user's earphones may be in use by other apps, so kana uses shared mode, which is the default. Nothing to add.

**Sample rates. Works unchanged.** WASAPI shared mode only opens a stream at the endpoint's mix-format rate (usually 48 kHz) unless `WasapiSettings(auto_convert=True)` is passed (sounddevice 0.4.7 and later). kana does not need that: `_pick_rate` tries 16 kHz (capture) and 24 kHz (playback), and when `check_*_settings` refuses, falls back to the device's `default_samplerate` and resamples linearly, which is exactly what it already does for 48 kHz devices on macOS. Pass-through opens at the device's native rate anyway.

**Channels. Unverified.** kana opens one channel. PortAudio's WASAPI backend converts mono to the mix format's channel count in shared mode (its own mono/stereo mixers), but this has to be seen working with VB-CABLE, whose default format is stereo.

**`latency="low"` and 10 ms blocks. Unverified.** On WASAPI shared mode "low" maps to the device's default period (normally 10 ms), so a 10 ms block is one period: the same shape as on macOS. Whether VB-CABLE adds its own buffering on top (it has an internal buffer, set in its control panel) has to be measured on a real machine with `tools/latency_bench.py`, the same way [LATENCY.md](../LATENCY.md) measured BlackHole. The engine now gives VB-Audio capture devices the same low-latency options as BlackHole; if Windows measurements say otherwise, `--capture-latency default` turns it off.

**Device-name matching. Needs a change (done in this branch).**

- VB-Audio names a cable's two ends differently. The playback end is "CABLE-A Input (VB-Audio Cable A)" and the recording end is "CABLE-A Output (VB-Audio Cable A)". The meeting app's microphone is therefore "CABLE-A **Output**", while kana writes to "CABLE-A **Input**". BlackHole has one name for both ends, so on macOS this never came up. The engine now accepts a name of either end: the defaults on Windows are the cable names `CABLE-A` and `CABLE-B` (each matches both ends; the direction picks input or output), and a user who types what Meet shows ("CABLE-A Output" for `--meet-mic`) gets the right end too. This fallback applies to virtual cables only, never to a physical device.
- MME truncates names to 31 characters: "CABLE-A Output (VB-Audio Cable A)" becomes "CABLE-A Output (VB-Audio Cable ". A full name saved by the app still matches a cut name under `--host-api mme`.
- The loop-safety check of `--passthrough` compared BlackHole names. It now recognises VB-Audio cables (and Muzychenko's Virtual Audio Cable, "Line 1 (Virtual Audio Cable)") and compares the two ends of one VB-Audio cable as one cable, so "earphones = a cable" and "write into the cable you capture" are refused on Windows as on macOS.

### 1.2 The two virtual cables

kana needs two independent loopback cables, each with exactly one writer and one reader ([ARCHITECTURE.md](../ARCHITECTURE.md#why-the-routing-cannot-loop)):

| Role | macOS | Windows (recommended) | Meet setting on Windows |
|---|---|---|---|
| kana's outbound translation → Meet's microphone | BlackHole 2ch | VB-CABLE **A** | Microphone: "CABLE-A Output (VB-Audio Cable A)" |
| Meet's speaker → kana's inbound direction | BlackHole 16ch | VB-CABLE **B** | Speakers: "CABLE-B Input (VB-Audio Cable B)" |

The candidates:

| Driver | Cables | Licence and cost | Can kana's Setup fetch it? | Signed for Secure Boot | Verdict |
|---|---|---|---|---|---|
| [VB-CABLE](https://vb-audio.com/Cable/) (VB-Audio) | 1 ("CABLE Input/Output") | Donationware: free to use, a donation is asked for. Publishers may bundle the package **as is** with attribution ("VB-CABLE by VB-Audio, donationware, vb-cable.com") as long as the end user can see it and donate. | Yes: a versioned zip (`VBCABLE_Driver_Pack46.zip`) on `download.vb-audio.com`, pinnable by SHA-256 like BlackHole. | Yes (Windows 10/11, x64 and Arm64 listed) | Free, but only one cable: not enough alone. |
| VB-CABLE A+B (VB-Audio) | 2 ("CABLE-A …", "CABLE-B …") | Donationware sold through VB-Audio's webshop (pay what you want); the download link is personal, sent after the donation. **"Cannot be distributed or bundled with other product."** | **No.** The user donates and installs it by hand. | Yes | **Recommended.** Two dedicated cables, one manual step. |
| [Virtual Audio Cable](https://vac.muzychenko.net/) (Eugene Muzychenko) | up to 256 | Paid per-user licence; the trial inserts a spoken reminder into the audio. | No (paid licence). | Yes | Supported by name if the user already owns it; not the default. |
| [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver) | a virtual speaker and a virtual mic | MIT (Microsoft sample parts MS-PL) | Would be, but | **No: beta, needs test signing.** The README does not describe the speaker as looped into the mic. | Not usable for end users. |
| Our own driver (SysVAD-derived) | any | ours | yes | Needs an EV certificate and Microsoft attestation signing; we have neither. | Out of scope. |

**Recommendation: VB-CABLE A+B, installed by the user.** It is the only option that gives two production-signed cables without kana redistributing anything it is not allowed to. Using A and B (not the free VB-CABLE) also leaves the free cable alone: many Windows users already use "CABLE Input/Output" for OBS or streaming, and sharing it with kana would break the one-writer-one-reader rule. A user who prefers the free VB-CABLE plus one other cable can pick any two cables in Setup (`--meet-mic`, `--meet-spk`); the engine treats them the same.

**The honest difference from macOS:** on macOS Setup installs both drivers with one click and one password prompt. On Windows the A+B pair needs a donation on VB-Audio's shop and a manual install (run `VBCable_AB_PackSetup.exe` as administrator, then reboot). Setup can only link to the shop page, explain the two steps, and detect the cables afterwards. If VB-Audio later grants permission to fetch or bundle A+B (their licensing page invites publishers to ask), the driver step can become one click, the same way `KANA_BUNDLE_DRIVERS` is prepared for BlackHole.

**A second route, later: WASAPI loopback for the inbound side.** Windows can capture what any render endpoint plays (endpoint loopback) and, since Windows 10 2004, what one process tree plays (process loopback). Inbound could then capture Chrome's output without a second cable, leaving only one free VB-CABLE for the outbound side, which Setup *can* download. Two problems keep this out of v1: stock PortAudio/sounddevice does not expose loopback devices (forks like PyAudioWPatch do), and with endpoint loopback Meet's untranslated audio would also reach the user's ears unless Meet plays to a device nobody listens to. Worth a spike after M2.

### 1.3 Windows audio settings that can bite

- **"Listen to this device"** (Sound control panel › Recording › a device › Listen) copies a recording endpoint to a playback endpoint inside Windows, outside kana. Enabled on CABLE-B Output it plays Meet's untranslated audio into the earphones; enabled on CABLE-A Output and pointed at CABLE-B Input it creates a real loop (kana → Meet mic → Windows → Meet speaker cable → kana). kana cannot see this through PortAudio. Setup should warn, and a later version can read the setting from the endpoint's property store.
- **Communications ducking.** Sound control panel › Communications defaults to "Reduce the volume of other sounds by 80%" when Windows detects a call. Chrome's WebRTC capture counts as one, so kana's playback into the earphones may drop by 80% the moment Meet opens its microphone. Setup must tell the user to choose "Do nothing". Unverified whether a WASAPI stream opened by kana is ducked (it opens with the default category).
- **Microphone privacy.** Settings › Privacy & security › Microphone › "Let desktop apps access your microphone" must be on; when it is off, WASAPI capture of a real microphone fails or delivers silence. This is the Windows equivalent of the macOS microphone permission. Virtual cable endpoints are capture devices too and are subject to the same switch. Unverified: the exact PortAudio error.
- **Default devices.** If the user leaves the Windows default output on a cable, every other app plays into kana's inbound path. The engine already refuses pass-through with a cable as earphones; Setup should also flag a cable as the system default.
- **Bluetooth headsets.** When any app opens a Bluetooth headset's microphone, Windows switches it to the hands-free profile (mono, 16 kHz), which also degrades what plays to it. Same as AirPods on macOS; the README advice ("use a separate mic or wired earphones for best quality") applies.

## 2. Paths, settings and platform services

| macOS | Windows | Status |
|---|---|---|
| `~/Library/Application Support/kana` (transcripts, `engine_path`) | `%LOCALAPPDATA%\kana`. Local, not Roaming: `engine_path` and device names are machine-specific, and transcripts should not sync with a roaming profile. | **Done** in `kana/paths.py`; `--save-dir` defaults to it per platform. |
| `.env` in the repo root and the working directory, `--env-file` | same, `python-dotenv` reads UTF-8 on every platform | Works unchanged. |
| stdout/stderr are UTF-8 | a piped stdout uses the ANSI code page (cp1252, cp932), which cannot encode every transcript and would crash the JSON protocol on the first Japanese line | **Done**: the engine reconfigures stdin/stdout/stderr to UTF-8 on Windows only. |
| terminal push-to-talk: `termios` cbreak + `loop.add_reader` | no `termios`; the default Proactor event loop has no `add_reader` | **Done**: a daemon thread reads keys with `msvcrt.getwch`. Unverified on a real console. |
| login Keychain (`KeychainStore.swift`), key passed to the engine in its environment | Windows Credential Manager, a generic credential per key (`kana/GEMINI_API_KEY`), protected by DPAPI for the user. Rust: the `keyring` crate; .NET: `CredWrite`; Python: `keyring`. The engine is unchanged: it still gets the key in its environment, never as an argument. | App work (M2). |
| talk key: Right ⌥ via `NSEvent` global monitor, needs Accessibility | A low-level keyboard hook (`SetWindowsHookEx(WH_KEYBOARD_LL)`); `RegisterHotKey` cannot watch a lone modifier. No permission prompt exists, but a hook gets no events while an elevated window (an admin console) has focus. | App work (M2), see caveats below. |
| `sharingType = .none` hides the panel from screen sharing | `SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)`, Windows 10 2004 (build 19041) and later; earlier builds only have `WDA_MONITOR`, which shows a black box. Applies to Chrome's screen share because Chrome captures through Windows Graphics Capture / DXGI, which honour the flag. | App work (M2). Unverified with Meet. |
| floating, non-activating `NSPanel` | a top-most window with `WS_EX_TOPMOST`, `WS_EX_NOACTIVATE` and `WS_EX_TOOLWINDOW` (no taskbar button, never steals focus from Meet) | App work (M2). |
| menu-bar icon | a notification-area (tray) icon. Windows 11 puts new icons in the overflow until the user pins them; Setup should say so. | App work (M2). |
| `open` to show a folder or a URL | `ShellExecute` / `explorer` | App only; the engine never calls `open`. |

**The engine has no other macOS-only code.** The driver installer (`DriverInstaller.swift`), `--driver-install-dry-run`, `--render-setup`, the Keychain and the audio self-test tone are all in the Swift app, not in `kana/`. The only engine test that is macOS-specific is the opt-in live test (`tests/test_live.py` uses `say`), which is skipped without a key.

**Talk key on Windows.** Right Alt is the natural twin of Right ⌥, but it has two problems:

1. On layouts with AltGr (most European layouts; not US or JIS), Right Alt is AltGr and arrives as Right Alt plus a synthetic Left Ctrl (scan code `0x21D`); the hook must ignore the fake Ctrl, and holding AltGr changes what other keys type.
2. A bare Alt press and release activates the menu bar of the focused window. In Chrome, where Meet runs, it moves focus to Chrome's menu button. The hook must either swallow the key or inject a dummy key between press and release (the "menu mask key" trick AutoHotkey uses), and either one has side effects.

So the Windows default should be **Right Ctrl** (no menu activation, no AltGr, present on US, European and JIS keyboards), with Right Alt offered as an option. The hold/tap logic (`TalkKeyLogic.swift`) is pure and ports line by line.

## 3. Engine packaging

**Recommended: python-build-standalone, assembled on the Mac.** The same approach as `app/bundle_engine.sh`:

- Runtime: `cpython-3.13.x+<tag>-x86_64-pc-windows-msvc-install_only.tar.gz` from astral-sh/python-build-standalone, pinned by SHA-256 (layout: `python/python.exe`, `Lib/`, `DLLs/`). An `aarch64-pc-windows-msvc` build exists too.
- Wheels: `pip install --target <runtime>/Lib/site-packages --platform win_amd64 --python-version 3.13 --implementation cp --only-binary=:all: .` runs on the Mac and pulls Windows wheels for `numpy`, `pydantic-core` (via `google-genai`), `websockets`, `sounddevice` (with its PortAudio DLL) and the pure-Python rest. No Windows machine is needed to build the bundle.
- Bytecode: compiled with the Mac's own Python 3.13 (`.pyc` is platform-independent for one minor version), `--invalidation-mode unchecked-hash` as today.
- The app runs `python.exe -m kana` with `CREATE_NO_WINDOW` so no console flashes. Not `pythonw.exe`: it has no stdout, and the protocol needs one.
- Expected size: 60 to 80 MB unpacked, like the macOS engine.

**Why not PyInstaller:** a one-file build unpacks itself to `%TEMP%` on every start (slow, and some corporate policies block executables there), and PyInstaller's bootloader is a frequent antivirus false positive. A plain runtime folder has neither problem and keeps the Mac and Windows pipelines the same.

**Arm64 Windows.** Unverified: `numpy` publishes `win_arm64` wheels, `sounddevice`'s Windows wheels carry x86 and x64 PortAudio DLLs only, as far as we can tell. x64 emulation on Windows 11 Arm would run the x64 bundle. v1 targets x64 only.

**Code signing: none.** An unsigned installer downloaded from GitHub gets SmartScreen's "Windows protected your PC" (More info › Run anyway), the counterpart of Gatekeeper's first-open steps. Reputation builds per file hash over time. Options later: Microsoft's Trusted Signing service (monthly fee; check whether a Japanese company is eligible) or an OV certificate from a CA. An EV certificate no longer skips SmartScreen reputation, so it is not worth the extra cost for this.

**Installer: MSIX vs Inno Setup vs NSIS vs a zip.**

| | MSIX | Inno Setup | NSIS (Tauri's bundler) | zip |
|---|---|---|---|---|
| Unsigned | cannot be installed (developer mode only) | fine, SmartScreen warns | fine, SmartScreen warns | fine, SmartScreen warns on the exe |
| Per-user, no admin | yes | yes | yes (`%LOCALAPPDATA%\Programs\kana`) | yes |
| Can start the driver installer | no (sandboxed) | yes | yes | n/a |
| Uninstall entry, Start menu | yes | yes | yes | no |
| Built from the Mac | no | under Wine only | Tauri builds NSIS installers when cross-compiling from macOS/Linux (marked experimental by Tauri) | yes |

Recommendation: a **zip** for M1/M2 testers, the **NSIS installer** Tauri generates for M3. MSIX is out while there is no signing. The installer never installs the VB-Audio driver itself (see 1.2); Setup inside the app handles that step.

## 4. The app

The Swift app does not port. Whatever replaces it speaks the existing JSON-lines protocol ([ENGINE.md](../ENGINE.md#json-protocol---json)) to the same engine, so the engine and its tests stay one codebase. The Windows app needs: a tray icon; a borderless, top-most, non-activating panel and mini bar; exclude-from-capture; a global talk key with hold and tap; credential storage; device pickers fed by `--list-devices --json`; a child process with stdin/stdout pipes; and an installer.

| Need | (a) C# WPF or WinUI 3 | (b) Tauri 2 (Rust + WebView2) | (c) Python + pywebview + pystray |
|---|---|---|---|
| Tray icon | WinForms `NotifyIcon` or a package (H.NotifyIcon) | built in (`tray-icon`) | `pystray`, which wants its own loop; pywebview wants the main thread; workable with `run_detached` but fiddly |
| Borderless, top-most, no-activate panel | native, full control | `decorations(false)`, `always_on_top`, `skip_taskbar`; `WS_EX_NOACTIVATE` through the raw HWND (`windows` crate) | pywebview `frameless`, `on_top`; `WS_EX_NOACTIVATE` through `ctypes` on the HWND |
| Exclude from capture | one P/Invoke | `set_content_protected(true)` (or one `SetWindowDisplayAffinity` call through the `windows` crate) | `ctypes` call on the HWND |
| Global talk key (lone modifier, hold/tap) | low-level hook by P/Invoke | low-level hook in Rust (about 100 lines; the global-shortcut plugin uses `RegisterHotKey` and cannot do it) | low-level hook by `ctypes` on a dedicated thread with a message loop |
| Credentials | `CredWrite` by P/Invoke | `keyring` crate | `keyring` package |
| Engine child process, JSON lines | `System.Diagnostics.Process` | sidecar (`tauri-plugin-shell`), line events on stdout, writes to stdin | `subprocess` |
| Installer and size | MSIX/MSI/Inno; a self-contained .NET app is 70 to 150 MB, framework-dependent needs the .NET runtime installed | NSIS or MSI built in; the shell is 5 to 10 MB (WebView2 is part of Windows 11 and of current Windows 10) | PyInstaller or the same Python runtime, plus WebView2; antivirus false positives common |
| Linux later | no (WPF/WinUI are Windows-only) | yes: same UI, WebKitGTK; tray and capture exclusion differ | partly |
| Team fit (Python and Swift) | C# is close to Swift, but a third UI codebase that only runs on Windows | UI in HTML/CSS/TypeScript, a thin Rust layer for the hook and window flags | one language, but the least predictable windowing |
| Build from the Mac | needs Windows (WPF/WinUI do not build on macOS) | cross-compile with `cargo-xwin` (experimental), or build on the VM | yes |

**Recommendation: (b) Tauri 2.** The tray, the borderless top-most windows, content protection and the sidecar process with stdin/stdout are all first-class in Tauri, so the Rust part shrinks to the talk-key hook, a few window flags and the credential calls. The web UI can later serve a Linux build (and could even replace parts of the SwiftUI panel), which neither WPF nor WinUI can. The costs: a Rust toolchain, WebView2 as a runtime dependency (preinstalled on Windows 11; the installer can bootstrap it on Windows 10), and window behaviours (no-activate, content protection on WebView2) that must be checked on a real machine.

## 5. Testing without a Windows machine

### 5.1 An Azure Windows VM (for M1 to M3)

- **Size: B2ms** (2 vCPU, 8 GB). B2s (4 GB) is too small for Windows 11, Chrome and a Meet call at once. Burstable B-series is fine: the engine is light, Chrome is the load, and tests are short.
- **Image:** Windows 11 Pro/Enterprise images on Azure need an eligible Windows licence (multitenant hosting rights) or a Visual Studio subscription image. Without one, Windows Server 2022/2025 Datacenter (licence included) works for M1/M2, with two extra steps: enable the Windows Audio service (disabled on Server by default) and install the Desktop Experience. Use Trusted Launch; the VB-Audio drivers are production-signed, so Secure Boot stays on.
- **VB-CABLE on a VM:** the drivers create their endpoints without any physical sound card, so the VM gets real WASAPI devices. The A+B licence covers one user's own machines; a second donation is not needed for a test VM, but check the terms.
- **Remote Desktop and audio:** with "Play on this computer", RDP adds a "Remote Audio" endpoint and can make it the default; with "Record from this computer" it adds a redirected microphone. Both change what PortAudio lists and add their own latency. For measurements set RDP to **"Do not play"** and no recording, so the VM has only its own endpoints. Then:
  - M1 round trip, no microphone and no Meet needed: engine 1 runs `--only out --out-file english.wav` and writes Japanese into CABLE-A; engine 2 runs `--only in --meet-spk CABLE-A --spk "CABLE Input" --dump-in back.wav` (the free VB-CABLE stands in for earphones) and translates it back to English. Both cables, WASAPI capture and playback, and the protocol are exercised; `back.wav` is the evidence. Latency with `tools/latency_bench.py`.
  - Pass-through refuses a cable as earphones by design, so pass-through listening tests use the "Remote Audio" endpoint (RDP set to "Play on this computer"), accepting its extra latency.
  - A real Meet call: the VM joins a meeting from Chrome, the owner joins from the Mac. The Mac side speaks, the VM side is driven by WAV files.
- **Cost (Japan East, pay-as-you-go, Azure retail prices read 2026-11-13):** B2ms with Windows licence $0.117/hour (B2s $0.062/hour). Deallocated, only the disk is billed: the default 127 GB OS disk as Standard SSD E10 is $9.60/month (Standard HDD S10 $5.89/month), plus a static public IP about $3.65/month (or none, with Bastion or a dynamic IP). **At 20 hours of use a month: about $2.30 compute + $9.60 disk + $3.65 IP ≈ $16/month (about ¥2,400).** A full test week at 8 hours a day adds about $6.50. Set auto-shutdown so a forgotten VM costs at most a day.

### 5.2 A real Windows PC (before any release claim)

The VM cannot answer: Bluetooth and USB headsets, real microphone latency through WASAPI, laptop power management, real keyboards (AltGr, JIS) for the talk key, the tray on a real taskbar, and SmartScreen on a real download. The owner's own PC (or a borrowed one) is required for M3 sign-off. Parallels on the owner's Apple silicon Mac runs Windows 11 Arm, which VB-CABLE supports, but it adds a virtual audio layer and runs the x64 engine under emulation, so it is a convenience for UI work, not a measurement platform.

## 6. Unverified, needs a Windows machine

1. WASAPI capture of VB-CABLE B at `latency="low"` with 10 ms blocks: the chunk delay, compared with BlackHole's 7 ms, and VB-CABLE's own internal buffer.
2. PortAudio's mono stream on a stereo VB-CABLE endpoint in shared mode (open succeeds, channel 0 carries Meet's audio).
3. Communications ducking: does Windows lower kana's earphone playback when Meet opens its microphone, and does "Do nothing" fix it.
4. `WDA_EXCLUDEFROMCAPTURE` on the panel, the mini bar and the caption strip during a Meet screen share in Chrome and Edge.
5. The talk key hook: Right Ctrl and Right Alt on US, JIS and an AltGr layout; no Chrome menu activation; behaviour while an elevated window has focus.
6. `WS_EX_NOACTIVATE` with WebView2: clicking the panel must not take focus from Meet.
7. The engine's console push-to-talk (`msvcrt.getwch` thread) in Windows Terminal and the classic console.
8. UTF-8 JSON over the pipe to the app, with Japanese device names and transcripts.
9. The VB-CABLE A+B install on Windows 11 with Secure Boot, the reboot, and the exact endpoint names after install.
10. SmartScreen and Defender behaviour on the unsigned installer and on the bundled `python.exe`.
11. Microphone privacy switch off: the error the engine reports.
12. Tauri cross-compilation of the NSIS installer from macOS, or the build moves to the VM.

## Sources

- VB-Audio: [VB-CABLE page](https://vb-audio.com/Cable/), [licensing](https://vb-audio.com/Services/licensing.htm), [reference manual](https://vb-audio.com/Cable/VBCABLE_ReferenceManual.pdf); A+B endpoint names as used in [PlayIt Live's guide](https://www.playitsoftware.com/FAQs/q/route-playit-live-audio-through-stereo-tool-using-virtual-cables).
- python-sounddevice: [platform-specific settings](https://python-sounddevice.readthedocs.io/en/0.5.3/api/platform-specific-settings.html) (`WasapiSettings`, `auto_convert` from 0.4.7); [issue #281](https://github.com/spatialaudio/python-sounddevice/issues/281) (no WASAPI loopback in stock PortAudio); [PyAudioWPatch](https://pypi.org/project/PyAudioWPatch) (a fork with loopback).
- The 31-character MME name limit: [wine-devel, 2021-01](https://list.winehq.org/pipermail/wine-devel/2021-January/179946.html).
- [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver) (MIT, beta, test signing).
- Azure prices: the public [Azure Retail Prices API](https://prices.azure.com/api/retail/prices), region `japaneast`, read 2026-11-13.
- `SetWindowDisplayAffinity` and `WDA_EXCLUDEFROMCAPTURE`: Microsoft Win32 documentation (Windows 10 version 2004 and later).
