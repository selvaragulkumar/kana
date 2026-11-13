#!/bin/bash
# Builds kana.app with Command Line Tools only (no Xcode).
#   app/build.sh                  -> app/build/kana.app (engine: a checkout, as before)
#   app/build.sh --install        -> also copies it to /Applications and records this repo as engine_path if none is set
#   app/build.sh --bundle-engine  -> also puts a self-contained Python engine inside the app (app/bundle_engine.sh)
#   app/build.sh --arch x86_64    -> builds for another architecture (default: this Mac's)
# Environment:
#   KANA_SIGN_IDENTITY   signing identity ("-" = ad-hoc); default: "kana Local Signing" if present, else ad-hoc
#   KANA_HARDENED=1      hardened runtime + secure timestamp + entitlements (for notarisation; release.sh sets it)
#   KANA_REUSE_ENGINE=1  reuse app/build/engine-<arch> instead of rebuilding it
#   KANA_BUNDLE_DRIVERS=1  put the BlackHole pkgs inside the app. Only with Existential Audio's
#                        permission: their compiled installers are not GPL (see app/drivers/README.md).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="kana"                    # visible app name, bundle and executable
PRODUCT="Kana"                 # SwiftPM target name
BUNDLE_ID="com.selvaragulkumar.kana"
VERSION="0.1.0"
OUT="$HERE/build"
APP="$OUT/$NAME.app"

INSTALL=0
BUNDLE_ENGINE=0
ARCH="$(uname -m)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) INSTALL=1; shift ;;
    --bundle-engine) BUNDLE_ENGINE=1; shift ;;
    --arch) ARCH="${2:-}"; shift 2 ;;
    --print-version) echo "$VERSION"; exit 0 ;;
    *) echo "usage: $0 [--install] [--bundle-engine] [--arch arm64|x86_64]" >&2; exit 64 ;;
  esac
done
case "$ARCH" in arm64|x86_64) ;; *) echo "unknown arch: $ARCH" >&2; exit 64 ;; esac

echo "==> swift build -c release ($ARCH)"
swift build -c release --arch "$ARCH" --package-path "$HERE"
BIN="$(swift build -c release --arch "$ARCH" --package-path "$HERE" --show-bin-path)/$PRODUCT"

echo "==> assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/$NAME"
if [[ -d "$HERE/Resources" ]]; then
  cp -R "$HERE/Resources/." "$APP/Contents/Resources/"   # fonts + their OFL licences
fi

if [[ $BUNDLE_ENGINE -eq 1 ]]; then
  ENGINE_SRC="$OUT/engine-$ARCH"
  if [[ "${KANA_REUSE_ENGINE:-0}" != 1 || ! -x "$ENGINE_SRC/python/bin/python3" ]]; then
    "$HERE/bundle_engine.sh" --arch "$ARCH"
  else
    echo "==> reusing $ENGINE_SRC"
  fi
  echo "==> bundling the engine"
  mkdir -p "$APP/Contents/Resources/engine"
  ditto "$ENGINE_SRC/python" "$APP/Contents/Resources/engine/python"
  cp "$ENGINE_SRC/VERSION" "$ENGINE_SRC/requirements.lock.txt" "$APP/Contents/Resources/engine/"
fi

if [[ "${KANA_BUNDLE_DRIVERS:-0}" == 1 ]]; then
  echo "==> bundling the BlackHole installers"
  "$HERE/fetch_drivers.sh" "$APP/Contents/Resources/drivers"
fi

if [[ ! -f "$HERE/icon.png" ]]; then
  echo "==> generating icon.png"
  swift "$HERE/make_icon.swift" "$HERE/icon.png"
fi

ICON_KEY=""
if [[ -f "$HERE/icon.png" ]]; then
  echo "==> icon from icon.png"
  ICONSET="$OUT/$NAME.iconset"
  rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$HERE/icon.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$HERE/icon.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$NAME.icns"
  rm -rf "$ICONSET"
  ICON_KEY="<key>CFBundleIconFile</key><string>$NAME</string>"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>kana captures your microphone and the Meet audio to translate them live.</string>
  $ICON_KEY
</dict>
</plist>
PLIST
plutil -lint "$APP/Contents/Info.plist" >/dev/null

# Sign with a stable identity when one exists (KANA_SIGN_IDENTITY, else a local "kana Local
# Signing" certificate), so macOS keeps the Accessibility and microphone grants across rebuilds.
# Ad-hoc signing changes the app's identity on every build and macOS forgets the grants.
IDENTITY="${KANA_SIGN_IDENTITY:-}"
if [[ -z "$IDENTITY" ]] && security find-identity -p codesigning 2>/dev/null | grep -q '"kana Local Signing"'; then
  IDENTITY="kana Local Signing"
fi
[[ -z "$IDENTITY" ]] && IDENTITY="-"
SIGN=(codesign --force --sign "$IDENTITY")
APP_ENT=()
ENGINE_ENT=()
if [[ "${KANA_HARDENED:-0}" == 1 ]]; then
  SIGN+=(--options runtime --timestamp)
  APP_ENT=(--entitlements "$HERE/entitlements/kana.entitlements")
  ENGINE_ENT=(--entitlements "$HERE/entitlements/engine.entitlements")
fi
if [[ "$IDENTITY" == "-" ]]; then
  echo "==> ad-hoc codesign (no stable identity; grants reset on rebuild)"
else
  echo "==> codesign with \"$IDENTITY\"${KANA_HARDENED:+ (hardened runtime)}"
fi

# Nested code first, inside out: every Mach-O in the bundled engine (extension modules,
# dylibs, then the interpreter), because codesign --deep does not reach Contents/Resources.
ENGINE_DIR="$APP/Contents/Resources/engine"
if [[ -d "$ENGINE_DIR" ]]; then
  LIBS=() EXES=()
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q "Mach-O"; then
      if [[ -x "$f" && "$f" != *.so && "$f" != *.dylib ]]; then EXES+=("$f"); else LIBS+=("$f"); fi
    fi
  done < <(find "$ENGINE_DIR" -type f -print0)
  echo "    $((${#LIBS[@]})) libraries, ${#EXES[@]} executable(s) in the engine"
  printf '%s\0' "${LIBS[@]}" | xargs -0 -n 50 "${SIGN[@]}" >/dev/null
  for f in "${EXES[@]}"; do
    "${SIGN[@]}" ${ENGINE_ENT[@]+"${ENGINE_ENT[@]}"} --identifier "$BUNDLE_ID.engine" "$f"
  done
fi
"${SIGN[@]}" ${APP_ENT[@]+"${APP_ENT[@]}"} --identifier "$BUNDLE_ID" "$APP"
codesign --verify --strict --deep "$APP"
if [[ -d "$ENGINE_DIR" ]]; then
  codesign --verify --strict "$ENGINE_DIR/python/bin/python3"
fi

if [[ $INSTALL -eq 1 ]]; then
  echo "==> installing to /Applications"
  rm -rf "/Applications/$NAME.app"
  cp -R "$APP" "/Applications/$NAME.app"
  echo "installed /Applications/$NAME.app"
  # An installed copy is no longer under <repo>/app/build, so record this repo as the engine
  # folder unless the user already chose one (Setup › Engine › Change… rewrites it). A build
  # with --bundle-engine prefers its own engine unless Setup says to use the checkout.
  ENGINE_FILE="$HOME/Library/Application Support/$NAME/engine_path"
  REPO="$(cd "$HERE/.." && pwd)"
  if [[ ! -s "$ENGINE_FILE" && -x "$REPO/.venv/bin/python" ]]; then
    mkdir -p "$(dirname "$ENGINE_FILE")"
    echo "$REPO" > "$ENGINE_FILE"
    echo "engine_path -> $REPO"
  fi
fi
du -sh "$APP" | awk '{print "app size: " $1}'
echo "done: $APP"
