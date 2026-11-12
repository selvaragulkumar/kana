# Open-source survey: live meeting translators (2026-11-12)

Scope: projects that do what Tsuyaku does (two-way live voice translation in a meeting app) or an adjacent part of it (live captions, virtual-mic routing, Gemini/OpenAI realtime translation). Star counts, languages, licences and last-push dates were read from the GitHub API on 2026-11-12. Features come from each README unless marked otherwise. "Unverified" means we could not confirm it from the repo.

What Tsuyaku is, for reference (from `README.md` and `docs/superpowers/specs/`): Python engine, two independent Gemini Live sessions on `gemini-3.5-live-translate-preview` (voice-preserving speech-to-speech), Japanese→English into the user's earphones and English→Japanese into Meet through BlackHole 2ch, Meet's speaker routed to BlackHole 16ch so the two paths cannot touch, push-to-talk (terminal space or global ⌃⌥Space), session resumption + go_away reconnect for hour-long calls, live cost meter in USD/JPY, native SwiftUI menu-bar app talking to the engine over JSON lines, a fake engine and WAV injection for tests.

---

## 1. The repos

| # | Repo | Stars | Stack | Licence | Last push |
|---|---|---|---|---|---|
| 1 | [kizuna-ai-lab/sokuji](https://github.com/kizuna-ai-lab/sokuji) | 1,489 | TypeScript, Electron + Chrome/Edge MV3 extension | AGPL-3.0 | 2026-11-11 |
| 2 | [wquguru/cicada](https://github.com/wquguru/cicada) | 2,187 | Swift/SwiftUI (Mac), plus Windows, Linux, Android ports | Apache-2.0 | 2026-11-12 |
| 3 | [SakiRinn/LiveCaptions-Translator](https://github.com/SakiRinn/LiveCaptions-Translator) | 4,052 | C# / WPF (Windows 11) | Apache-2.0 | 2026-08-17 |
| 4 | [himomohi/AirTranslate](https://github.com/himomohi/AirTranslate) | 484 | Swift (macOS 26+) | Apache-2.0 | 2026-10-22 |
| 5 | [franklioxygen/v2s](https://github.com/franklioxygen/v2s) | 511 | Swift menu-bar app | README says MIT; API reports no licence file (LICENSES/ dir) | 2026-10-11 |
| 6 | [KazKozDev/live-translation](https://github.com/KazKozDev/live-translation) | 44 | Python + PyObjC overlay, MLX Whisper, Ollama | MIT | 2026-10-04 |
| 7 | [thehwang/Scripta](https://github.com/thehwang/Scripta) | 19 | Swift, whisper.cpp, Ollama | MIT | 2026-09-29 |
| 8 | [jasoncheng7115/jt-live-whisper](https://github.com/jasoncheng7115/jt-live-whisper) | 593 | Python, local models, Swift ScreenCaptureKit helper | Apache-2.0 | 2026-11-08 |
| 9 | [TheDeathDragon/LiveTranslate](https://github.com/TheDeathDragon/LiveTranslate) | 908 | Python (Windows), faster-whisper/SenseVoice + LLM | MIT | 2026-08-17 |
| 10 | [roirude/LiveLingo](https://github.com/roirude/LiveLingo) | 6 | Python (Windows), Whisper→LLM→Edge TTS→VB-Cable | MIT | 2026-05-29 |
| 11 | [PolyTalkIO/polytalk](https://github.com/PolyTalkIO/polytalk) | 78 | Python FastAPI + browser, Docker | AGPL-3.0 | 2026-07-06 |
| 12 | [livekit-examples/gemini-live-translate](https://github.com/livekit-examples/gemini-live-translate) | 23 | Next.js + LiveKit Agents (Python) + Gemini Live | MIT | 2026-10-29 |
| 13 | [google-gemini/gemini-live-api-examples](https://github.com/google-gemini/gemini-live-api-examples) | 576 | JS/Python samples | no licence file | 2026-11-10 |
| 14 | [fossasia/voxbento](https://github.com/fossasia/voxbento) | 1,533 | Python, event interpretation platform | Apache-2.0 | 2026-11-12 |
| 15 | [SamirPaulb/real-time-voice-translator](https://github.com/SamirPaulb/real-time-voice-translator) | 442 | Python Tkinter, Google Translate + gTTS | GPL-2.0 | 2026-05-04 |
| 16 | [collabora/WhisperLive](https://github.com/collabora/WhisperLive) | 4,356 | Python streaming Whisper server (building block) | MIT | 2026-11-11 |
| 17 | [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) | 3,680 | Python streaming Whisper (building block) | MIT | 2025-11-12 |
| 18 | [ExistentialAudio/BlackHole](https://github.com/ExistentialAudio/BlackHole) | 20,043 | C, CoreAudio HAL driver (our routing dependency) | GPL-3.0 | 2026-11-07 |

Also relevant but not a standalone repo: the OpenAI cookbook's realtime translation guide with browser, Twilio and LiveKit demos on `gpt-realtime-translate` ([guide](https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide)), and Google's Live Translate docs ([ai.google.dev](https://ai.google.dev/gemini-api/docs/live-api/live-translate)).

### Per-repo notes

**Sokuji** (the closest competitor). Two-way speech translation for meetings with a "speaker client" (your mic → their language) and a "participant client" (their audio → your language), described in [docs/SYSTEM_AUDIO_CAPTURE.md](https://github.com/kizuna-ai-lab/sokuji/blob/main/docs/SYSTEM_AUDIO_CAPTURE.md). Eight providers: OpenAI, Gemini, Palabra, Kizuna AI, Doubao, Soniox, OpenAI-compatible, and fully local WASM/WebGPU inference (44 ASR, 75 translation, 137 TTS models). Its Gemini provider recognises `live-translate` models ([settings.ts](https://github.com/kizuna-ai-lab/sokuji/blob/main/src/providers/gemini/settings.ts)), and code search finds push-to-talk and Gemini session resumption. Routing on macOS: they ship their own HAL driver, `SokujiVirtualAudio.driver`, built from a BlackHole submodule and installed by the `.pkg` postinstall ([pkg-scripts/postinstall](https://github.com/kizuna-ai-lab/sokuji/blob/main/pkg-scripts/postinstall)). Inbound is captured as all system audio through `electron-audio-loopback`, or per tab in the extension. UX: Electron window, Simple/Advanced modes, 30 UI languages, Chrome Web Store extension for Meet. Weaknesses: Electron footprint; macOS capture is "all system audio", not per app; PostHog analytics; very large surface (30 releases, many providers) so any one path gets less polish; no live cost meter found (searched, unverified). README quality: centred logo, badge row, mermaid flow, demo video, install matrix, DeepWiki badge, ja/zh READMEs, CONTRIBUTING + issue templates, CHANGELOG, THIRD_PARTY_NOTICES, SignPath code signing on Windows.

**Cicada (知了)**. Native SwiftUI menu-bar app: live bilingual subtitles, live structured meeting notes (summary, to-dos, fishbone, glossary), and "simultaneous interpreting": hold right ⌥ and your translated voice goes into the call. Outbound only: inbound is subtitles, not speech. One-click BlackHole 2ch download (SHA-256 verified, not bundled because of the GPL) and automatic switch of the system mic while interpreting ([README](https://github.com/wquguru/cicada)). Hands-free mode with meeting-audio ducking and a 1-second pause trigger. Voice cloning from an 8-30 s sample with a Ling key; otherwise macOS voices. On-device ASR (Apple SpeechAnalyzer), Google Translate for partials, Ling LLM for sentences. On-device speaker diarization (WeSpeaker on Core ML). Notes window hidden from screen sharing. Records export to Markdown, Word, SRT. Weaknesses: its interpreting is a cascade (ASR → text → TTS), so no voice preservation without the Ling cloud; inbound has no audio; not notarised; default cloud is a Chinese provider, which some users cannot sign up for. README quality is the best in the set: icon, tagline, big "Website" and "Download" badges, platform badges, demo GIF, screenshots per feature, permissions table, "transparent networking" host list, models table, roadmap, uninstall, en/zh/ja/ko READMEs, checksums in releases, AGENTS.md, own website.

**LiveCaptions-Translator**. The most-starred translator in the set. It drives Windows 11's built-in Live Captions and sends the text to Google/DeepL/LLM translators, showing a click-through overlay. Text only, Windows only, no voice out. Wins on "one click from Releases" and a clean badge row, GIF, Fluent UI screenshots.

**AirTranslate**. macOS caption + translation app with ScreenCaptureKit system audio, Apple on-device default, and many optional engines including Gemini Live and `gpt-realtime-translate`. Optional translated speech output (Apple, Gemini TTS, MAI Voice). Keys in Keychain, protected-terms glossary, floating text-only captions with five styles, transcript library. Weaknesses: README is a release-note wall (the first screen is 1.17.0 file transcription detail); macOS 26+ only. Ships DMG + `.sha256`, four README languages.

**v2s**. Menu-bar bilingual subtitle bar, on-device Apple Speech + Apple Translation, per-app audio capture (not whole system mix), Silero VAD on Core ML, Apple Intelligence summaries. Has a Homebrew tap (`brew install --cask franklioxygen/v2s/v2s`) and an in-app updater with `appcast.xml` (Sparkle-style). No voice. macOS 26+.

**KazKozDev/live-translation**. Python + PyObjC glass overlay, BlackHole + Multi-Output Device for capture, MLX Whisper + Gemma via Ollama, fully offline. Captions only. Strong README habits worth copying: a one-line ASCII pipeline in "TL;DR", a "Who is this for?" list, a "How it is different" section, an honest limitations list, `setup.sh` + `Brewfile`, pinned `requirements.lock.txt`.

**Scripta**. Native Swift meeting transcriber: mic via whisper.cpp ("You") and system audio via Apple speech ("Remote"), Ollama summaries and chat, scheduled recordings, live translation on macOS 15+. Text only. Good demo habit: a 90-second YouTube walkthrough thumbnail at the top.

**jt-live-whisper**. Huge local toolkit (live transcription, translation, diarization, summaries, TTS) for Mac/Windows/Linux, ScreenCaptureKit on Mac so no driver. Has a bidirectional voice-interpreting mode with VoxCPM2 TTS (README, mostly in Traditional Chinese). Thousand-line README, no releases, installer scripts. Shows the cost of feature sprawl.

**TheDeathDragon/LiveTranslate**. Windows WASAPI loopback, multiple ASR engines, streaming LLM translation, overlay, built-in benchmark, remote ASR on a GPU box, portable zip build. Captions only.

**LiveLingo**. Closest in spirit to our outbound path on Windows: mic → Whisper → LLM → Edge TTS → VB-Cable as Teams' mic. Cascade, robotic voice, one direction. Clear step-by-step README with a device glossary ("CABLE Input is a playback device...").

**PolyTalk CE**. Self-hosted browser speech-to-speech with faster-whisper + any LLM + Piper TTS, Docker Compose, and a mock mode that runs without keys. No meeting routing. Full community-file set: CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, SUPPORT, issue + PR templates.

**livekit-examples/gemini-live-translate**. One Gemini Live session per (speaker, target language) pair inside a LiveKit room, publishing `tx:<speaker>:<lang>` audio tracks and caption streams. The cleanest public reference for Gemini Live Translate session handling, but it is its own video-call app, not a bridge into Meet. README has a mermaid diagram and an annotated repo tree.

**google-gemini/gemini-live-api-examples**. Official command-line, ephemeral-token and Python SDK samples. Not a product; no licence file.

**voxbento** (FOSSASIA). Event interpretation platform (rooms, relays, RTMPS), not a personal meeting tool. Details beyond the description are unverified.

**real-time-voice-translator**. Older Tkinter desktop app (Google Translate + gTTS, MSI installer from 2023). Its "preserves tone and emotion" claim is in the description; we did not verify it.

**WhisperLive / whisper_streaming**. Building blocks for local streaming ASR, relevant only if we ever add an offline fallback.

**BlackHole**. Our routing dependency, GPL-3.0. Cicada downloads it at runtime instead of bundling; Sokuji forks it into a renamed driver.

---

## 2. Comparison table

| Project | Voice out to meeting | Translated voice to you | Voice preserved | Meeting routing | Model / pipeline | UI | Push-to-talk | Long-call resumption | Cost meter | Notarised install |
|---|---|---|---|---|---|---|---|---|---|---|
| **Tsuyaku (ours)** | Yes | Yes (earphones) | Yes (Gemini Live Translate) | BlackHole 2ch mic + 16ch speaker, per meeting app | Gemini 3.5 Live Translate, one-step S2S | Native SwiftUI menu bar + CLI | Yes, global hotkey | Yes | Yes, USD/JPY live | No (ad-hoc) |
| Sokuji | Yes | Yes ("Translation I hear") | Only on providers that clone (Palabra, Doubao, Soniox); Gemini LT supported | Own forked BlackHole driver; system-wide loopback; Chrome tab capture | 8 providers incl. Gemini LT, OpenAI, local WASM | Electron + browser extension | Yes | Yes (Gemini) | Not found | Windows signed (SignPath); Mac pkg unverified |
| Cicada | Yes | No (subtitles) | Only with Ling voice clone | One-click BlackHole 2ch, auto-switch system mic | Apple ASR → LLM → TTS; Ming one-step with key | Native SwiftUI menu bar | Yes (right ⌥) + hands-free | n/a | No | No (checksums) |
| LiveCaptions-Translator | No | No | n/a | Windows Live Captions | Google/DeepL/LLM text | WPF overlay | n/a | n/a | No | Signed unverified |
| AirTranslate | No | Optional TTS | No | ScreenCaptureKit | Apple, Gemini Live, OpenAI, Qwen... | Native app + floating captions | No | Unverified | Pricing info only | No (checksums) |
| v2s | No | No | n/a | Per-app capture | Apple on-device | Native menu bar | n/a | n/a | n/a | No (Homebrew tap) |
| KazKozDev live-translation | No | No | n/a | BlackHole + Multi-Output | MLX Whisper + Ollama | PyObjC overlay | n/a | n/a | n/a | No |
| Scripta | No | No | n/a | ScreenCaptureKit + mic | whisper.cpp + Apple + Ollama | Native app | n/a | n/a | n/a | Unverified |
| jt-live-whisper | Bidirectional TTS mode | Yes (TTS) | No | ScreenCaptureKit / WASAPI / PipeWire | Local Whisper + LLM + VoxCPM2 | CLI + overlay + WebUI | Unverified | n/a | n/a | n/a |
| LiveLingo | Yes | No | No | VB-Cable (Windows) | Whisper → LLM → Edge TTS | CLI | Unverified | n/a | No | n/a |
| PolyTalk CE | No (browser) | Yes (browser) | No | None | Whisper + LLM + Piper | Web | No | n/a | No | Docker |
| livekit gemini-live-translate | In its own rooms | In its own rooms | Yes (Gemini LT) | LiveKit tracks | Gemini Live Translate | Next.js web | No | Unverified | No | n/a |

---

## 3. What they have that we don't, ranked by value to a daily user

1. **A real installer and a guided first run.** Cicada installs BlackHole with one click and switches the system mic itself. Sokuji's `.pkg` installs its own driver. Ours needs Homebrew, a venv, a pip line, a `.env` file and three manual Meet settings. This is the largest daily-friction gap and the first thing a new user hits.
2. **Floating captions over the meeting.** Cicada, v2s, AirTranslate, LiveCaptions-Translator and TheDeathDragon all keep the translation on screen above other apps. Our transcript lives inside the menu-bar panel, which closes when Meet is in front. Reading the English while hearing it is the best fallback when a word is lost.
3. **Saved meeting records and export.** Cicada (Markdown, Word, SRT, searchable history), Scripta, AirTranslate. Ours prints and forgets.
4. **Hide our window from screen sharing.** Cicada hides its notes window from screen capture by default. In Meet you share your screen often, and a transcript panel leaking into the share is a real embarrassment.
5. **Glossary / protected terms.** Cicada's word list and AirTranslate's protected terms keep names and product terms spelled right. Company and person names are where live translation fails most visibly.
6. **Hands-free mode with ducking.** Cicada starts sending when you talk and ducks meeting audio. Useful for long one-on-ones where holding a key is tiring.
7. **Signed, notarised build with auto-update.** v2s has an appcast-based updater and a Homebrew tap; Sokuji has Squirrel auto-update. Our ad-hoc signature also makes macOS forget the Accessibility grant on rebuild.
8. **API key in Keychain.** AirTranslate stores keys in Keychain; Cicada restricts file permissions. Ours is a plaintext `.env`.
9. **Speaker labels.** Cicada (on-device WeSpeaker) and jt-live-whisper separate speakers. Less important for one-to-one calls.
10. **Provider choice / offline fallback.** Sokuji and AirTranslate offer many engines and local models. Lower value for us: our point is the one model that preserves voice, and we already have a `--model` fallback.
11. **Localised UI and README in Japanese.** Cicada, Sokuji, AirTranslate. Matters if we want Japanese users.
12. **Browser-extension delivery.** Sokuji's Chrome extension captures the Meet tab with no virtual devices at all. Big for reach, large build.

## 4. What we have that none of them do

Honest framing first: Sokuji covers the same concept and already supports the Gemini Live Translate model. What no single project combines is the following.

- **Voice-preserving translation in both directions with audio on both ends.** Inbound English is spoken into your earphones in a voice mirrored from the Japanese speaker, and outbound Japanese carries your voice into Meet. Cicada's inbound is text; Sokuji only preserves voice on some providers; the LiveKit example only works inside its own rooms.
- **Loop-proof routing by construction.** Meet's speaker is a dedicated device (BlackHole 16ch) and Meet's mic another (BlackHole 2ch), so the engine only ever hears Meet and only Meet hears the outbound voice. Sokuji's macOS participant leg captures all system audio; we could not verify how it avoids hearing its own inbound playback.
- **A live cost meter in USD and JPY.** No project we read shows running spend. AirTranslate only shows a pricing basis per model.
- **Silent on same-language speech.** With `echo_target_language=False`, if the user speaks Japanese the outbound stays silent, and if the other side speaks English the inbound stays silent. Code-switching works without a language switch.
- **Native Swift shell over a scriptable engine.** The JSON-lines protocol means the same engine runs headless from a terminal, from tests, or under the app. Cicada and v2s are native but monolithic; Sokuji is Electron.
- **Test seams without audio or a key.** WAV injection for both directions and a fake engine for the app. Only PolyTalk's mock mode is comparable.
- **No telemetry, small enough to audit in an afternoon.** Six Python and six Swift files. Sokuji ships PostHog analytics.

---

## 5. Concrete improvement list

Effort is focused engineering hours for one person who knows the codebase.

| # | Improvement | Effort | Why |
|---|---|---|---|
| 1 | Rename everything to Tsuyaku (package, app bundle, bundle id, README, Application Support folder) and keep a `meet_translate` alias for one release | 2 h | The repo still says meet-translate and MeetTranslate; a public project needs one name. |
| 2 | Remove personal specifics before publishing: GCP project name in README, the home-folder default engine path in the spec and app | 1 h | Required before the repo goes public. |
| 3 | Hide the panel from screen capture (`NSWindow.sharingType = .none`), with an opt-in toggle | 0.5 h | Cicada does it; protects users when they share their screen in Meet. |
| 4 | Gate inbound audio with a local voice-activity detector so silence is not streamed and billed | 4 h + a measured call | Input is billed per second sent; meetings are mostly silence for one direction. Measure cost before and after on a recorded call. |
| 5 | Latency readout per direction (source transcript time to first translated audio) next to the cost meter | 3 h | Nobody shows latency; it is the number users feel. Makes tuning honest. |
| 6 | Setup doctor in the app: detect both BlackHole devices, offer the install command, play a test tone through BlackHole 2ch and read it back, show a checklist for the Meet settings | 5 h | Turns the wiring table into a one-screen check; closes most of gap 1 without a driver of our own. |
| 7 | API key onboarding with Keychain storage and a one-call key test | 4 h | Removes `.env` editing; matches AirTranslate. |
| 8 | Floating caption strip for inbound English (click-through, top or bottom of screen, hidden from capture) | 6-8 h | Second most valuable daily feature from the survey. |
| 9 | Save each call as Markdown (both columns, timestamps) and SRT, with an "Open last transcript" menu item | 3 h | Meeting record without building a notes product. |
| 10 | Glossary: names and terms passed to the fallback model as a system instruction; check whether Live Translate accepts any context and document the answer | 3 h | Names are the most visible failure; Live Translate may not accept prompts, so verify before promising it. |
| 11 | Hands-free outbound mode: VAD opens the mic, inbound playback ducks while you talk, PTT stays the default | 6 h | Cicada's best interpreting idea; keep the anti-goal (never send while the user believes they are muted) by showing state loudly. |
| 12 | Bundle the Python engine inside the app (python-build-standalone + vendored wheels) | 8-12 h | No venv, no Homebrew Python; prerequisite for a DMG anyone can install. |
| 13 | Developer ID signing + notarisation + DMG + `checksums.txt` | 4 h + USD 99/yr | Stops Gatekeeper prompts and the lost Accessibility grant after each rebuild. |
| 14 | Homebrew cask in a tap (`brew install --cask <owner>/tap/tsuyaku`) that depends on the BlackHole casks | 2 h | v2s pattern; one line installs app and drivers. |
| 15 | Sparkle auto-update with an appcast in releases | 4 h | v2s and Sokuji both auto-update. |
| 16 | Reconnect chaos test: kill the socket mid-utterance and assert resumption and no duplicated audio | 3 h | Our claim is "survives a one-hour call"; prove it in tests. |
| 17 | Language-pair presets beyond ja/en in the panel | 1 h | The engine already takes any BCP-47 pair. |
| 18 | Japanese README (README.ja.md) | 2 h | Half the target conversation is Japanese speakers; Cicada, Sokuji and AirTranslate all do this. |

Suggested order: 1-3 before the repo is public, then 4-7 (cost, latency, setup, key), then 8-9, then the distribution items 12-15.

---

## 6. Repo-presentation checklist

Each item names the repo it is borrowed from.

- [ ] Centred icon, name, one-line tagline, then a badge row for licence, latest release, macOS version (Cicada, Sokuji, LiveCaptions-Translator).
- [ ] Two large call-to-action badges, "Download" and "Website" (Cicada).
- [ ] Demo GIF or 60-90 s video above the fold showing both directions with sound captions on screen (Cicada `docs/demo.gif`, Sokuji demo video, Scripta's 90-second YouTube walkthrough).
- [ ] A one-line ASCII pipeline in a "TL;DR" block (KazKozDev/live-translation).
- [ ] A mermaid diagram of the two directions and four devices, replacing the ASCII box from the spec (Sokuji, livekit-examples/gemini-live-translate).
- [ ] "Who is this for" and "How it is different" sections (KazKozDev/live-translation).
- [ ] Requirements table: macOS version, Apple silicon/Intel, BlackHole, Gemini key (Cicada platforms table).
- [ ] Install in three ways: DMG from Releases with SHA-256 `checksums.txt` (Cicada, AirTranslate), Homebrew cask tap (v2s), build from source (all).
- [ ] Wiring explained with a device glossary: which device is a playback device and which is a recording device (LiveLingo's VB-Cable section).
- [ ] Privacy and permissions table: each macOS permission, why, what breaks without it (Cicada).
- [ ] "Transparent networking": the exact hosts the app talks to, and that there is no telemetry (Cicada).
- [ ] Models table: default, fallback, what each does (Cicada).
- [ ] Cost section with per-minute numbers and the meter screenshot (ours; nobody else has it).
- [ ] Honest limitations section: preview model, lag of a few seconds, no speaker labels, Meet settings are manual (KazKozDev/live-translation).
- [ ] Annotated repo layout tree (livekit-examples/gemini-live-translate).
- [ ] Uninstall section, including the BlackHole drivers and Application Support folder (Cicada).
- [ ] README.ja.md with a language switcher line (Cicada, Sokuji, AirTranslate).
- [ ] CHANGELOG.md and tagged releases with notes (Cicada, Sokuji, KazKozDev).
- [ ] docs/ROADMAP.md linked from the README (Cicada).
- [ ] CONTRIBUTING.md, issue templates (bug with device list + engine log, feature request), PR template (Sokuji, PolyTalk, Scripta).
- [ ] SECURITY.md stating how keys are stored and how to report issues (PolyTalk, voxbento).
- [ ] THIRD_PARTY_NOTICES.md covering BlackHole (GPL-3.0, not bundled) and Python deps (Sokuji, v2s).
- [ ] GitHub topics: `macos`, `menubar-app`, `swiftui`, `gemini`, `gemini-live-api`, `live-translation`, `simultaneous-interpretation`, `speech-to-speech`, `google-meet`, `blackhole`, `japanese` (Sokuji and Scripta use 15-20 topics).
- [ ] Social preview image set in repo settings, and a small GitHub Pages site later (Cicada `site/`, v2s and jt-live-whisper Pages).
- [ ] AGENTS.md or ARCHITECTURE.md for contributors and coding agents, linking the two specs (Cicada).
- [ ] CI badge: most of these repos run GitHub Actions for builds. Our standing rule is no GitHub Actions, so either leave the badge out and document `pytest` + `app/build.sh` as the local gate, or get an explicit exception for this public repo. Needs a decision from the owner.

## 7. Licence recommendation

**Apache-2.0.** It is permissive like MIT, adds an explicit patent grant and a NOTICE file convention, matches Cicada, AirTranslate and LiveCaptions-Translator, and matches `google-genai`, the SDK we depend on. AGPL (Sokuji, PolyTalk) would discourage the people most likely to fork a personal tool into their own workflow.

Constraints to respect:
- BlackHole is GPL-3.0. Do not bundle or fork the driver into our app. Install it through the official Homebrew casks or download it from the official URL, as Cicada does, and say so in THIRD_PARTY_NOTICES. If we ever ship a renamed driver like Sokuji, that component must be distributed under GPL-3.0 with source.
- The Gemini model is a preview under Google's API terms; the README should say that the user brings their own key and is billed by Google.

## 8. Taglines and blog angles

Repo descriptions (GitHub "About" field):
1. "Two-way live voice translation for Google Meet on macOS. You speak English, they hear Japanese, in your own voice."
2. "A menu-bar interpreter for any meeting app: Gemini Live Translate in both directions, routed through BlackHole, loop-proof by design."
3. "Your voice, their language. Real-time speech-to-speech translation for calls, from the Mac menu bar."
4. "Simultaneous interpretation for one person and one Mac. Push to talk, hear the other side in English, see what it costs per minute."
5. "通訳 in your menu bar: live Japanese⇄English voice translation for Meet, Zoom and Teams."

Blog-post angles for selvaragulkumar.com/writing (engineer-builder voice, technical, honest):
1. **"Four audio devices and no feedback loop."** Why two BlackHole devices make the loop impossible rather than unlikely, with the wiring diagram and the bug you get with one device.
2. **"What a one-hour call costs."** Real per-minute numbers from the cost meter, what silence costs before and after voice gating, and when the bill beats hiring an interpreter.
3. **"Keeping a Live API session alive for an hour."** Session caps, go_away, resumption handles, context compression, and what the user hears during a reconnect.
4. **"A SwiftUI shell over a Python engine, talking JSON lines."** Why not port the audio code to Swift, how the fake engine made the UI testable without a microphone, and what the Liquid Glass panel cost.
5. **"I surveyed every open-source live translator. Here is why I still built my own."** The landscape above, what Sokuji and Cicada do better, and the one thing none of them do: your voice in both directions.
