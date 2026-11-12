## What and why

<!-- What this changes and why. Link the issue and, for anything bigger than a bug fix, the spec in docs/superpowers/specs/. -->

## Local gate

There is no CI. Paste the last lines of each command's output.

```text
$ .venv/bin/python -m pytest -q

$ app/build.sh

```

- [ ] I ran `pytest -m live` because this touches `kana/session.py` or the model config (or it does not).
- [ ] I tried it in the app, with the real engine or `app/fake_engine.py`, if the app changed.

## Checklist

- [ ] JSON protocol changes update `docs/ENGINE.md`, the app, `app/fake_engine.py` and `tests/test_events.py` together (or there are none).
- [ ] No audio feedback loop becomes possible, and the microphone is never sent while the user believes they are muted.
- [ ] No new network host, no telemetry.
- [ ] Files staged by explicit path; no `.env`, WAV dumps or build output.
- [ ] `CHANGELOG.md` has an entry under Unreleased if users will notice the change.
- [ ] No files under `.github/workflows/`.
