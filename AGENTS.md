# AGENTS.md

Notes for coding agents and new contributors. Humans should also read [CONTRIBUTING.md](CONTRIBUTING.md).

## Where things are

- `kana/`: Python engine (`python -m kana`, console script `kana`).
- `app/`: Swift menu-bar app, built by `app/build.sh` into `app/build/kana.app`. `app/fake_engine.py` stands in for the engine.
- `tests/`: pytest suite for the engine.
- `docs/ARCHITECTURE.md`: devices, process model, loop-proof routing, session lifetime, test seams.
- `docs/ENGINE.md`: flags, the JSON-lines protocol between app and engine, voice gate, latency and cost measurements.
- `docs/REGISTER.md`: the outbound Japanese register evaluation behind `--register`.
- `design/`: logo, mark and app icon sources (SVG). `app/icon.png` is rendered from `design/kana-app-icon.svg`.
- `docs/superpowers/specs/`: design specs, one per feature. Write or extend one before a non-trivial change.
- `docs/research/`: background research. `docs/ROADMAP.md`: what comes next.

## Rules

- **No GitHub Actions.** Do not add files under `.github/workflows/`. The gate is local.
- **Stage by explicit path.** `git add path/to/file`, never `git add -A` or `git add .`. Other agents may be writing in the same tree, and `.env` and WAV dumps must never be committed.
- **Protocol changes touch four places in one change:** `docs/ENGINE.md`, the app, `app/fake_engine.py` and `tests/test_events.py`.
- **Anti-goals:** no audio feedback loops by construction, and never send the microphone while the user believes they are muted.
- **No telemetry.** The engine talks only to `generativelanguage.googleapis.com` (or, with the opt-in `--backend vertex`, to `aiplatform.googleapis.com` and Google's OAuth token endpoint for application-default credentials), or to `api.openai.com` instead when the user picks `--provider openai`. The app makes one kind of network call: when the user presses **Install audio drivers** in Setup, it downloads the two BlackHole installers from `existential.audio` (pinned version and SHA-256, see `app/drivers/README.md`). Nothing else.
- **Installer work never runs for real on a dev Mac.** Test the driver install with `kana --driver-install-dry-run` (prints the admin command, installs nothing) and the Setup page with `kana --render-setup <dir>` (offscreen).
- Never print or log `GEMINI_API_KEY` or `OPENAI_API_KEY`. The app passes it to the engine in the environment, never as an argument.

## Test commands

```sh
.venv/bin/python -m pytest -q          # unit tests, no key or audio needed
.venv/bin/python -m pytest -m live -s  # real Gemini call, needs GEMINI_API_KEY, costs cents
app/build.sh                           # builds the app with Command Line Tools only
app/build.sh --bundle-engine           # same, with its own Python engine inside (as in the DMG)
app/release.sh                         # dist/kana-<version>.dmg
```
