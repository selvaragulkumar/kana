# Roadmap

What comes after 0.1.0, roughly in order. Each item has a one-line reason. The reasoning behind the list is in [research/2026-11-12-open-source-survey.md](research/2026-11-12-open-source-survey.md). Nothing here is promised by a date.

Already shipped in 0.1.0 and therefore not listed: the Setup doctor, the Keychain key, floating captions, hiding from screen sharing, the latency readout, language presets and saved transcripts. See [CHANGELOG.md](../CHANGELOG.md).

## Daily use

1. **Hands-free mode with ducking.** Voice activity opens the outbound path, and inbound playback ducks while you talk. Push-to-talk stays the default and the state is always shown loudly. *Why:* holding a key through a long one-on-one is tiring.
2. **Glossary.** Names and product terms passed to the models as instructions. Live Translate accepts an instruction but only partly honours it (see [REGISTER.md](REGISTER.md)), so this needs measuring before it is promised. *Why:* names are where live interpretation fails most visibly.
3. **Key check against Google.** The Setup page checks only the key's format today. A real one-call check through the engine would catch a revoked or mistyped key before a meeting. *Why:* a bad key should fail in Setup, not at the start of a call.

## Distribution

4. **Bundled Python.** Ship the engine inside the app with python-build-standalone and vendored wheels. The app already looks for a bundled engine. *Why:* no venv and no Homebrew Python, which a downloadable app needs.
5. **Notarised DMG.** Developer ID signing, notarisation, a DMG and `checksums.txt` on each release. *Why:* no Gatekeeper warning, and macOS stops forgetting the Accessibility grant after every rebuild.
6. **Homebrew tap.** `brew install --cask` from a tap that depends on the BlackHole casks. *Why:* one line installs the app and both drivers.
7. **Sparkle updates.** In-app updates from an appcast published with each release. *Why:* users get fixes without visiting GitHub.

## Docs

8. **Keep README.ja.md in step.** Every change to the English README gets the same change in [README.ja.md](../README.ja.md). *Why:* half of every conversation kana was built for is in Japanese.
