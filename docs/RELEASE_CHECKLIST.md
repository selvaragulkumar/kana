# Release checklist

Steps for making the repository public and tagging 0.1.0. Work top to bottom and tick each box in the release PR.

## Before the first push

- [ ] Confirm the GitHub owner. The docs use `selvaragulkumar/kana`. If it changes, replace it everywhere: `grep -rn "selvaragulkumar/kana" --exclude-dir=.venv .`
- [x] Remove the temporary `tsuyaku/` engine alias and its test, and drop it from `pyproject.toml` (done in engine commit 7ef3fad).
- [ ] Search for personal details and secrets in the tree and in the history:
  ```sh
  grep -rn -E "/Users/|zag-pios|AIza[0-9A-Za-z_-]{30,}" --exclude-dir=.venv --exclude-dir=.git --exclude=RELEASE_CHECKLIST.md .
  git log -p --all | grep -E "AIza[0-9A-Za-z_-]{30,}"
  git ls-files | grep -E "\.env$|\.wav$|\.aiff$"
  ```
  Each command must print nothing. On 2026-11-12 the first one still finds the GCP project name and a home-folder path in the two specs under `docs/superpowers/specs/` and in the survey, and the history holds an older README with the project name. Decide whether to edit those files and whether to publish from a fresh, squashed history.
- [ ] The bundled fonts in `app/Resources/Fonts/` are committed, each with its `OFL.txt`, and match [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
- [ ] `app/icon.png` is rendered from `design/kana-app-icon.svg`.
- [ ] No files under `.github/workflows/`.

## Local gate

- [ ] `.venv/bin/python -m pytest -q` passes.
- [ ] `app/build.sh` builds `kana.app`.
- [ ] `.venv/bin/python -m pytest -m live -s` passes with a real key.
- [ ] The app runs against `app/fake_engine.py` and against the real engine.
- [ ] **First live Google Meet call.** Run one real call in each direction. Then update the "Status" line near the top of both READMEs.

## Assets

- [ ] Record `docs/demo.gif`. What it must show is in the comment above the top image in [README.md](../README.md). No real participants' faces or names. Until then both READMEs show `docs/images/panel-live.png`; swap the GIF in at the top of both.
- [ ] Re-take the screenshots in `docs/images/` if the panel changes. They were cropped to leave out the rest of the menu bar; keep it that way.
- [ ] Make a social preview image (1280 × 640) from the design files in `design/`.

## Repository settings on GitHub

- [ ] **About:** description "kana — live Japanese ⇄ English interpreting", website if there is one.
- [ ] **Topics:** `macos`, `menubar-app`, `swiftui`, `gemini`, `gemini-live-api`, `live-translation`, `simultaneous-interpretation`, `speech-to-speech`, `google-meet`, `blackhole`, `japanese`, `interpreter`.
- [ ] **Social preview:** upload the image above (Settings › General).
- [ ] **Private vulnerability reporting:** turn it on (Settings › Code security). [SECURITY.md](../SECURITY.md) relies on it.
- [ ] **Actions:** disable them (Settings › Actions › General). The project has no workflows by decision.
- [ ] **Issues:** on. Wiki and Projects: off unless needed.

## Tag the release

- [ ] In [CHANGELOG.md](../CHANGELOG.md), turn "0.1.0 (first public release, not yet tagged)" into `## [0.1.0] - YYYY-MM-DD` and add the compare link.
- [ ] Check that both READMEs still match the code: flags, defaults, prices and the dated cost table.
- [ ] Tag `v0.1.0` and publish a GitHub release with the changelog section as notes.

## Optional

- [ ] **Apple Developer ID** (USD 99 per year) for a signed, notarised DMG with `checksums.txt`. Until then the README says "Download (coming)". See [ROADMAP.md](ROADMAP.md).
