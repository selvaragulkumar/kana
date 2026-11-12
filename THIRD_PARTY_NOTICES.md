# Third-party notices

kana is licensed under Apache-2.0 (see [LICENSE](LICENSE)). It depends on the software below. Each item keeps its own licence. Versions are the ones the project was last tested with; any compatible version works.

## Bundled inside kana.app

These files are copied into `kana.app/Contents/Resources/Fonts/` by `app/build.sh`. Their licence texts ship next to them.

| Component | Licence | Source |
|---|---|---|
| Inter (variable font), UI text | SIL Open Font License 1.1 | [github.com/rsms/inter](https://github.com/rsms/inter), licence: [app/Resources/Fonts/Inter/OFL.txt](app/Resources/Fonts/Inter/OFL.txt) |
| Noto Sans JP (variable font), Japanese text | SIL Open Font License 1.1 (Adobe, Reserved Font Name "Source") | [github.com/notofonts/noto-cjk](https://github.com/notofonts/noto-cjk), licence: [app/Resources/Fonts/NotoSansJP/OFL.txt](app/Resources/Fonts/NotoSansJP/OFL.txt) |
| Space Grotesk (variable font), wordmark | SIL Open Font License 1.1 | [github.com/floriankarsten/space-grotesk](https://github.com/floriankarsten/space-grotesk), licence: [app/Resources/Fonts/SpaceGrotesk/OFL.txt](app/Resources/Fonts/SpaceGrotesk/OFL.txt) |

The OFL allows bundling the fonts with software. The fonts are not sold on their own, and their reserved names are not used for anything else.

## Bundled inside the DMG build of kana.app

`app/release.sh` (via `app/bundle_engine.sh`) puts a Python runtime and the engine's dependencies into `kana.app/Contents/Resources/engine/python/`. Each keeps its licence: the CPython licence is at `lib/python3.13/LICENSE.txt` and each package's licence files are in `lib/python3.13/site-packages/<package>.dist-info/`. The exact versions are listed in `Contents/Resources/engine/requirements.lock.txt`.

| Component | Licence | Source |
|---|---|---|
| CPython 3.13, built by [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | PSF License (CPython); python-build-standalone is MPL-2.0 (build scripts only). The runtime includes OpenSSL (Apache-2.0), SQLite (public domain), libffi (MIT), XZ (0BSD), zlib (Zlib), bzip2 (bzip2 licence), libedit/ncurses (BSD/MIT-style) | [python.org](https://www.python.org/), [github.com/astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone) |
| The Python packages listed under [Python engine dependencies](#python-engine-dependencies) and their dependencies (pydantic, httpx2, websockets, cryptography, cffi, google-auth and others) | each its own: MIT, BSD, Apache-2.0 | PyPI |

## Installed on the user's request, never bundled

| Component | Licence | How it gets onto your Mac |
|---|---|---|
| [BlackHole](https://github.com/ExistentialAudio/BlackHole) 2ch and 16ch virtual audio drivers, by Existential Audio | Source: [GPL-3.0](app/drivers/BlackHole-LICENSE.txt). Official compiled installers: all rights reserved by Existential Audio | Setup's **Install audio drivers** downloads Existential Audio's official installers from `existential.audio` (the URLs and SHA-256 of the Homebrew casks) and runs them with your password. Or install them yourself: `brew install --cask blackhole-2ch blackhole-16ch`. |

kana does not contain, modify or fork any BlackHole code, and the DMG does not contain the BlackHole installers: their licence reserves the compiled installers, so kana fetches them from the vendor on the user's request, as Homebrew does. kana only opens the two devices by name through the normal macOS audio APIs. Source for BlackHole 0.7.1: [github.com/ExistentialAudio/BlackHole/tree/v0.7.1](https://github.com/ExistentialAudio/BlackHole/tree/v0.7.1). Details: [app/drivers/README.md](app/drivers/README.md).

## Python engine dependencies

Installed into your virtual environment by `pip` from PyPI for a source build, or into the app's own runtime for the DMG. They are not vendored in this repository.

| Package | Licence | Source |
|---|---|---|
| [google-genai](https://pypi.org/project/google-genai/) | Apache-2.0 | [github.com/googleapis/python-genai](https://github.com/googleapis/python-genai) |
| [sounddevice](https://pypi.org/project/sounddevice/) | MIT | [github.com/spatialaudio/python-sounddevice](https://github.com/spatialaudio/python-sounddevice) |
| PortAudio (shipped inside the sounddevice wheel on macOS as `libportaudio.dylib`) | PortAudio licence (MIT-style) | [portaudio.com](https://www.portaudio.com/license.html), [github.com/PortAudio/portaudio](https://github.com/PortAudio/portaudio) |
| [numpy](https://pypi.org/project/numpy/) | BSD-3-Clause (with bundled parts under 0BSD, MIT, Zlib, CC0-1.0) | [github.com/numpy/numpy](https://github.com/numpy/numpy) |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | BSD-3-Clause | [github.com/theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |

`google-genai` pulls in its own dependencies (for example `httpx`, `pydantic`, `websockets`, `google-auth`). Run `pip-licenses` or `pip show <name>` inside the venv for the full transitive list.

## Development and test tools

Used only when you run the tests. Not needed to run kana.

| Tool | Licence | Source |
|---|---|---|
| [pytest](https://pypi.org/project/pytest/) | MIT | [github.com/pytest-dev/pytest](https://github.com/pytest-dev/pytest) |
| [pytest-asyncio](https://pypi.org/project/pytest-asyncio/) | Apache-2.0 | [github.com/pytest-dev/pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) |
| [FFmpeg](https://ffmpeg.org/) (installed with Homebrew, used by the live test to convert a `say` recording) | LGPL-2.1+ / GPL-2.0+ depending on the build | [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html) |

## The Gemini API

kana calls the Gemini Developer API with your own API key. Your use of the API and its models is governed by Google's terms, not by this repository's licence: [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms). Google bills your key directly.
