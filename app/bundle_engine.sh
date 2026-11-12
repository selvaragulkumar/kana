#!/bin/bash
# Builds a relocatable engine for kana.app: a python-build-standalone CPython 3.13 runtime with
# the kana package and its dependencies installed into it (not editable, no venv).
#   app/bundle_engine.sh [--arch arm64|x86_64]   -> app/build/engine-<arch>/python/bin/python3
# The runtime tarball is downloaded once into app/build/cache and checked against a pinned
# SHA-256. build.sh --bundle-engine copies the result to kana.app/Contents/Resources/engine/.
# x86_64 runs pip under Rosetta (arch -x86_64), so it needs Rosetta on an Apple silicon Mac.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
CACHE="$HERE/build/cache"

# python-build-standalone release (github.com/astral-sh/python-build-standalone), install_only.
PBS_TAG="20261110"
PY_VERSION="3.13.18"
SHA_aarch64="1afd3983237c2a10277345f235be730e9cb49a123e0574ed252dbf3a841a24e4"
SHA_x86_64="a46bcdeecd28ba253522b321dcb3806da1b0ff581479fc1d27e9613e3ac44764"

ARCH="$(uname -m)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--arch arm64|x86_64]" >&2; exit 64 ;;
  esac
done
case "$ARCH" in
  arm64|aarch64) ARCH=arm64; TRIPLE=aarch64; RUN=(env) ;;
  x86_64) TRIPLE=x86_64; RUN=(arch -x86_64) ;;
  *) echo "unknown arch: $ARCH" >&2; exit 64 ;;
esac
SHA_VAR="SHA_$TRIPLE"
WANT_SHA="${!SHA_VAR}"

TARBALL="cpython-${PY_VERSION}+${PBS_TAG}-${TRIPLE}-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${TARBALL//+/%2B}"
OUT="$HERE/build/engine-$ARCH"
export PYTHONDONTWRITEBYTECODE=1   # only compileall below writes bytecode

mkdir -p "$CACHE"
if [[ ! -f "$CACHE/$TARBALL" ]]; then
  echo "==> downloading $TARBALL"
  curl -fsSL --retry 3 -o "$CACHE/$TARBALL.part" "$URL"
  mv "$CACHE/$TARBALL.part" "$CACHE/$TARBALL"
fi
GOT_SHA="$(shasum -a 256 "$CACHE/$TARBALL" | cut -d' ' -f1)"
if [[ "$GOT_SHA" != "$WANT_SHA" ]]; then
  echo "SHA-256 mismatch for $TARBALL: got $GOT_SHA, want $WANT_SHA" >&2
  rm -f "$CACHE/$TARBALL"
  exit 1
fi

echo "==> unpacking Python $PY_VERSION ($ARCH) into $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"
tar -xzf "$CACHE/$TARBALL" -C "$OUT"          # -> $OUT/python/
PY="$OUT/python/bin/python3"
"${RUN[@]}" "$PY" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'

# Install from a clean copy of the package, so pip never writes build/ or *.egg-info into the repo.
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/kana-engine-src.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp "$REPO/pyproject.toml" "$REPO/LICENSE" "$STAGE/"
cp -R "$REPO/kana" "$STAGE/kana"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "==> pip install kana and its dependencies"
PIP_CONFIG_FILE=/dev/null PYTHONNOUSERSITE=1 "${RUN[@]}" "$PY" -m pip install \
  --disable-pip-version-check --no-warn-script-location --no-compile --prefer-binary \
  --only-binary=numpy,sounddevice "$STAGE"
"${RUN[@]}" "$PY" -m pip freeze --disable-pip-version-check --exclude pip --exclude kana > "$OUT/requirements.lock.txt"

echo "==> trimming the runtime"
P="$OUT/python"
LIB="$P/lib/python3.13"
rm -rf "$P/include" "$P/share" "$P/lib/pkgconfig" \
       "$P"/lib/tcl* "$P"/lib/tk* "$P"/lib/itcl* "$P"/lib/thread* "$P"/lib/libtcl* "$P"/lib/libtk* \
       "$LIB/test" "$LIB/idlelib" "$LIB/tkinter" "$LIB/turtledemo" "$LIB/turtle.py" "$LIB/ensurepip" \
       "$LIB"/lib-dynload/_tkinter*.so "$LIB"/lib-dynload/_test*.so "$LIB"/lib-dynload/xxlimited*.so \
       "$LIB"/config-3.13-darwin/*.a
"${RUN[@]}" "$PY" -m pip uninstall -y -q --disable-pip-version-check pip
# Console scripts carry absolute build-machine shebangs; the app only runs bin/python3.
find "$P/bin" -mindepth 1 ! -name python3 ! -name python3.13 ! -name python -exec rm -rf {} +
rm -f "$LIB"/site-packages/*.dist-info/direct_url.json
find "$LIB/site-packages" -type d -name tests -prune -exec rm -rf {} +
find "$P" -name __pycache__ -type d -prune -exec rm -rf {} +

# The app bundle is read-only and signed, so bytecode is compiled now (unchecked-hash: valid
# without comparing source mtimes) and the engine runs with PYTHONDONTWRITEBYTECODE=1.
echo "==> compiling bytecode"
"${RUN[@]}" "$PY" -W ignore::SyntaxWarning -m compileall -q -f -j 0 --invalidation-mode unchecked-hash \
  -s "$LIB" -p "kana.app/Contents/Resources/engine/python/lib/python3.13" "$LIB" >/dev/null

# Nothing from the build machine (home folder, temp paths) may end up in the bundle.
if grep -rIl --exclude=requirements.lock.txt -e "$HOME" -e "${TMPDIR:-/nonexistent}" "$OUT" | head -5 | grep . ; then
  echo "build-machine paths leaked into the engine (above)" >&2; exit 1
fi
LEAK="$(grep -rlaF "$HOME/" "$OUT" | head -5 || true)"
if [[ -n "$LEAK" ]]; then echo "build-machine paths leaked into: $LEAK" >&2; exit 1; fi

echo "==> self-check"
(cd / && PYTHONNOUSERSITE=1 "${RUN[@]}" "$PY" -P -c 'import kana, numpy, sounddevice, google.genai, dotenv; print("engine imports OK:", kana.__file__)')
echo "$PY_VERSION $PBS_TAG $ARCH" > "$OUT/VERSION"
du -sh "$OUT" | awk '{print "engine size: " $1}'
echo "done: $OUT"
