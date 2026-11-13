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
- [ ] `app/build.sh --bundle-engine` builds, and the bundled engine runs from inside the app:
  ```sh
  P=app/build/kana.app/Contents/Resources/engine/python/bin/python3
  (cd / && env -i PYTHONSAFEPATH=1 PYTHONDONTWRITEBYTECODE=1 "$OLDPWD/$P" -m kana --help)
  (cd / && env -i PYTHONSAFEPATH=1 PYTHONDONTWRITEBYTECODE=1 "$OLDPWD/$P" -m kana --list-devices --json)
  codesign --verify --strict --deep app/build/kana.app
  ```
- [ ] `app/build/kana.app/Contents/MacOS/kana --driver-install-dry-run` downloads and verifies both BlackHole installers and prints the admin command. It installs nothing.
- [ ] `app/build/kana.app/Contents/MacOS/kana --render-setup /tmp/kana-setup` renders the five Setup states; look at them.
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

## DMG

- [ ] Versions agree: `VERSION` in `app/build.sh`, `version` in `pyproject.toml`, the CHANGELOG heading.
- [ ] BlackHole is still at the version pinned in `app/Sources/Kana/DriverInstaller.swift` and `app/fetch_drivers.sh`, with the sums from `https://formulae.brew.sh/api/cask/blackhole-2ch.json` and `…/blackhole-16ch.json`. If not, update both files and `app/drivers/` (see its README).
- [ ] Consider a newer python-build-standalone release (pin `PBS_TAG`, `PY_VERSION` and both SHA-256 values in `app/bundle_engine.sh` from the release's `SHA256SUMS`).
- [ ] Build: `app/release.sh --arch all` makes `dist/kana-<version>.dmg` (Apple silicon), `dist/kana-<version>-intel.dmg` and `dist/checksums.txt`.
- [ ] Upload every release with the stable names too: copies of the two DMGs as `kana-mac.dmg` and `kana-mac-intel.dmg`, so `https://github.com/selvaragulkumar/kana/releases/latest/download/kana-mac.dmg` keeps working from the website (done for 0.1.1). Signing identity: `KANA_SIGN_IDENTITY`, else the local "kana Local Signing" certificate, else ad-hoc.
- [ ] Notarised build, once there is a Developer ID: `xcrun notarytool store-credentials kana-notary` once, then `KANA_SIGN_IDENTITY="Developer ID Application: … (TEAMID)" KANA_NOTARY_PROFILE=kana-notary app/release.sh --arch all`. It turns on the hardened runtime with `app/entitlements/`, notarises and staples. Without both variables the script skips notarisation and says so.
- [ ] Mount the DMG without Finder (`hdiutil attach -nobrowse -readonly <dmg>`) and check: `kana.app` and an `Applications` link, `codesign --verify --strict --deep`, and the bundled engine command above from the mounted path.
- [ ] Fresh-Mac test (script for the tester: [FRESH_MAC_TEST.md](FRESH_MAC_TEST.md)), on a Mac or VM that has never had kana, BlackHole or Python from Homebrew: download the DMG from the draft release, drag to Applications, open (Gatekeeper steps from the README if not notarised), press **Install audio drivers**, and confirm that both devices appear without a log-out. Then save a key, allow the microphone and Accessibility, and run one Meet call. Note the macOS version in the release notes.
- [ ] Attach both DMGs and `checksums.txt` to the GitHub release. Say "not notarised: right-click › Open (macOS 14) or Privacy & Security › Open Anyway (macOS 15+)" next to the links until a Developer ID build exists.

## Tag the release

- [ ] In [CHANGELOG.md](../CHANGELOG.md), turn "0.1.0 (first public release, not yet tagged)" into `## [0.1.0] - YYYY-MM-DD` and add the compare link.
- [ ] Check that both READMEs still match the code: flags, defaults, prices and the dated cost table.
- [ ] Tag `v0.1.0` and publish a GitHub release with the changelog section as notes.

## Optional

- [ ] **Apple Developer ID** (USD 99 per year) so the DMG is notarised and opens without the Gatekeeper steps. `app/release.sh` is ready for it (see DMG above). See [ROADMAP.md](ROADMAP.md).
- [ ] **Licence from Existential Audio** to ship the BlackHole installers inside the DMG (then `KANA_BUNDLE_DRIVERS=1 app/release.sh`, and the install works offline). Without it, Setup downloads them from the vendor. See [app/drivers/README.md](../app/drivers/README.md).
