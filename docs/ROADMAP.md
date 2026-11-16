# Roadmap

What comes after 0.1.0, roughly in order. Each item has a one-line reason. The reasoning behind the list is in [research/2026-11-12-open-source-survey.md](research/2026-11-12-open-source-survey.md). Nothing here is promised by a date.

Already shipped in 0.1.0 and therefore not listed: the Setup doctor, the Keychain key, floating captions, hiding from screen sharing, the latency readout, language presets and saved transcripts. See [CHANGELOG.md](../CHANGELOG.md).

## Daily use

- **Transcript pairing under overlapping turns.** Seen again in the second real call (Zoom, 2026-11-16, ~40 min): long inbound turns showed the Japanese source in one row with no translation and the English in the next rows with "..." as source. Display only; the audio was fine (~1 s, stable). Top priority.
  *Status 2026-11-16: fixed on branch `kana-pairing-v2`, not yet released.* The cause was the engine's own sentence buffer, not the model (docs/research/transcription-timing.md); pairing v2 pairs chunks as they stream (docs/superpowers/specs/2026-11-16-pairing-v2.md) and every call now saves a raw `.events.jsonl` for replay. Still to do: replay the next real call's events log and check a sample of rows by hand (real crosstalk and Zoom audio are unmeasured), and measure the outbound direction, `--register business` and `--provider openai`.
- **Inbound voice and overlapping speakers.** In the 2026-11-16 call the rendered inbound voice changed mid-turn while the same person spoke, and a second speaker who started while the first turn was still being rendered was not heard. Investigate turn handling in the inbound session (one turn in flight; what happens to audio that arrives during output) and whether a voice setting, rather than voice matching, is steadier.
- **Survive meeting-app audio dropouts.** 2026-11-16: the engine stopped at a short Zoom reconnect (the meeting went on for several more minutes untranslated). Reopen the capture/playback streams on device or stream errors instead of exiting; the per-call events log will show the exact reason.
- **Translate Japanese whichever side hears it.** 2026-11-16: with Zoom's devices swapped for the first 3.5 minutes, the room's Japanese reached the mic path and was shown untranslated. Detect "target language on the mic path at session start" and warn that the meeting app's devices look swapped; consider routing it to the inbound translator.
- **Do not re-voice the listener's own language.** 2026-11-16: English spoken in the room came back as English in the earphones (about 2 minutes). When the inbound source is already the user's language, show it but do not play it.
- **Per-call glossary.** 2026-11-16 accuracy check (157 passages scored against an independent transcript, mean 1.90/3): most low scores were mishearings of names and counters (one counter misheard about eight times broke a pricing explanation). A short list of names and terms per call, given to the model where the provider allows it (business register already carries an instruction), would fix roughly half.
- **Number and negation guard.** 14 errors had a correct source but a wrong translation: 7 negation flips, 2 hundred-fold errors on 万/億. A per-turn check of numerals, magnitudes and negatives between source and translation, with a caption correction when they differ.
- **Merge sentence tails and back-channels.** 27 English rows were split-off sentence tails; 239 of 819 rows were bare はい-type acknowledgements. Merge tails into the previous row; collapse runs of back-channels.
- **(older note)** In the first real call (docs/VERIFICATION.md, 2026-11-13) a translation was shown beside the following source when turns overlapped and mixed languages. Pair by utterance id from the engine rather than by arrival order.

1. **Hands-free mode with ducking.** Voice activity opens the outbound path, and inbound playback ducks while you talk. Push-to-talk stays the default and the state is always shown loudly. *Why:* holding a key through a long one-on-one is tiring.
2. **Glossary.** Names and product terms passed to the models as instructions. Live Translate accepts an instruction but only partly honours it (see [REGISTER.md](REGISTER.md)), so this needs measuring before it is promised. *Why:* names are where live interpretation fails most visibly.
3. **Key check against Google.** The Setup page checks only the key's format today. A real one-call check through the engine would catch a revoked or mistyped key before a meeting. *Why:* a bad key should fail in Setup, not at the start of a call.

## Distribution

4. **Bundled Python.** Ship the engine inside the app with python-build-standalone and vendored wheels. The app already looks for a bundled engine. *Why:* no venv and no Homebrew Python, which a downloadable app needs.
5. **Notarised DMG.** `app/release.sh` already builds the DMG (bundled engine, one-click drivers) and `checksums.txt`, and notarises when given a Developer ID; what is missing is the Developer ID itself. *Why:* no Gatekeeper warning, and macOS stops forgetting the Accessibility grant after every rebuild.
6. **Homebrew tap.** `brew install --cask` from a tap that depends on the BlackHole casks. *Why:* one line installs the app and both drivers.
7. **Sparkle updates.** In-app updates from an appcast published with each release. *Why:* users get fixes without visiting GitHub.
8. **Windows.** The same engine and protocol with a Tauri 2 tray app and VB-Audio's VB-CABLE A+B as the two cables; milestones and the checks that need a real Windows machine are in [superpowers/specs/2026-11-13-windows-design.md](superpowers/specs/2026-11-13-windows-design.md), the audit in [research/windows.md](research/windows.md). *Why:* the owner asked for "the same one for Windows too", and many Meet users are on Windows.

## Docs

9. **Keep README.ja.md in step.** Every change to the English README gets the same change in [README.ja.md](../README.ja.md). *Why:* half of every conversation kana was built for is in Japanese.
