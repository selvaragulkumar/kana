# Contributing to kana

Thanks for helping. kana is small on purpose: one Python engine, one Swift menu-bar app, and a JSON-lines protocol between them. Please keep it that way.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first. It explains the two directions, the four audio devices and why the routing cannot loop.

## Development setup

You need macOS 14 or later, Python 3.13, Homebrew and the Xcode Command Line Tools (`xcode-select --install`). Xcode itself is not needed.

```sh
git clone https://github.com/selvaragulkumar/kana.git
cd kana
brew install portaudio ffmpeg
brew install --cask blackhole-2ch blackhole-16ch   # asks for your Mac password
python3.13 -m venv .venv
.venv/bin/pip install -e . pytest pytest-asyncio
```

`ffmpeg` is only used by the live test and the WAV examples. BlackHole is only needed to run real calls, not to run the unit tests.

For live runs from the terminal, put a Gemini API key in `.env` at the repository root (see [SECURITY.md](SECURITY.md)). The app can instead keep the key in the Keychain from its Setup page.

```sh
printf 'GEMINI_API_KEY=%s\n' 'your-key' > .env && chmod 600 .env
```

## The local gate

There is no CI in this repository. Before you open a pull request, run both of these and paste the last lines of their output into the PR:

```sh
.venv/bin/python -m pytest -q     # unit tests; no key, no audio devices, no network
app/build.sh                      # builds app/build/kana.app
```

The live test calls the real Gemini Live API and costs a few cents. It is skipped unless `GEMINI_API_KEY` is set, and it needs macOS `say` and `ffmpeg`:

```sh
.venv/bin/python -m pytest -m live -s
```

Run it when you change anything in `kana/session.py` or the model configuration. For changes to the outbound Japanese register, also run `tests/register_eval.py` and compare against [docs/REGISTER.md](docs/REGISTER.md).

### Testing without audio hardware

- **WAV injection (engine).** `--in-file x.wav` replaces the meeting capture and `--out-file x.wav` replaces your microphone. `--dump-in` and `--dump-out` save the translated audio. Combine them with `--only in` or `--only out` to test one direction.

  ```sh
  say -v Kyoko -o /tmp/ja.aiff "こんにちは、今日は天気がいいですね。"
  ffmpeg -y -i /tmp/ja.aiff -ar 16000 -ac 1 /tmp/ja.wav
  .venv/bin/python -m kana --only in --in-file /tmp/ja.wav --dump-in /tmp/en.wav
  ```

- **Fake engine (app).** `app/fake_engine.py` speaks the JSON protocol with canned transcripts, a reconnect, a non-fatal error and cost ticks. It needs no key, no audio and no network. Point the app at it with the `KANA_ENGINE_CMD` environment variable. Quit the running app first, because `open` reuses a running instance.

  ```sh
  open --env KANA_ENGINE_CMD="/usr/bin/python3 $PWD/app/fake_engine.py" app/build/kana.app
  ```

  Add `--env FAKE_ENGINE_FATAL=1` to see how a fatal engine error is shown.

## How to add a language pair

The engine already accepts any pair the model supports. Languages are BCP-47 codes:

```sh
.venv/bin/python -m kana --in en --out ko    # you hear English, the meeting hears Korean
```

`--in` is the language you hear and `--out` is the language the meeting hears. Each direction sets `target_language_code` on its own Live session, so no other engine change is needed for the default Live Translate model.

What else to touch, depending on the change:

1. **Fallback model.** `gemini-3.8-live` is driven by a system instruction that names the target language in English. Add the code and its English name to `LANG_NAMES` in `kana/session.py`. Unknown codes fall back to the raw code, which works but reads worse. `--register business` only affects the outbound direction when it is Japanese, because the keigo instruction (`KEIGO_INSTRUCTION`) is written for Japanese. A business register for another language needs its own instruction and its own evaluation like [docs/REGISTER.md](docs/REGISTER.md).
2. **App.** The language menu's presets live in `LanguagePresets` in the panel source under `app/Sources/`. Add the code and its English name there. **Custom…** already accepts any BCP-47 pair, so a preset is a convenience, not a requirement. The app passes the codes straight through as `--in` and `--out`.
3. **Tests.** Add a case to `tests/test_session.py` for the config that `build_config` produces with the new target.
4. **Live check.** Run one real WAV through `--only in` and listen to the dump. Note the result in the PR.

## The JSON protocol is a contract

The app and the engine talk over JSON lines: events on the engine's stdout, commands on its stdin. Any change to an event, a field or a command must, in the same pull request:

1. update [docs/ENGINE.md](docs/ENGINE.md), the protocol reference;
2. update the app (`app/Sources/`) to read or send it;
3. update `app/fake_engine.py`, so the app can still be tested without the real engine;
4. add or update a test in `tests/test_events.py`.

Add fields rather than renaming them. The app ignores fields and events it does not know.

## Specs before code

Design specs live in [docs/superpowers/specs/](docs/superpowers/specs/), one file per feature, named `YYYY-MM-DD-<topic>-design.md`. For anything bigger than a bug fix, write or extend a spec first and link it from the PR. A spec states the intent, goals, non-goals, anti-goals and what "done" means.

Two anti-goals apply to every change:

- No audio feedback loops. The device wiring must make a loop impossible, not just unlikely.
- Never send the user's microphone while they believe they are muted.

## Commit style

- One logical change per commit. The subject is an imperative sentence of at most 72 characters, for example `Engine: emit latency per direction`.
- Prefix with the area when it helps: `Engine:`, `App:`, `Tests:`, `Docs:`.
- The body says why, not what. Wrap at 72 characters.
- Stage files by explicit path. Do not use `git add -A` or `git add .`; it picks up `.env`, WAV dumps and build output too easily.
- Do not commit `.env`, `*.wav`, `*.aiff` or `app/build/`. They are in `.gitignore`.

## GitHub Actions

This repository has no GitHub Actions workflows, by decision. Please do not add any. The local gate above is the gate.

## Code of conduct

Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE), the same as the rest of the project.
