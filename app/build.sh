#!/bin/bash
# Builds kana.app with Command Line Tools only (no Xcode).
#   app/build.sh            -> app/build/kana.app
#   app/build.sh --install  -> also copies it to /Applications and records this repo as engine_path if none is set
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="kana"                    # visible app name, bundle and executable
PRODUCT="Kana"                 # SwiftPM target name
BUNDLE_ID="com.selvaragulkumar.kana"
VERSION="0.3.0"
OUT="$HERE/build"
APP="$OUT/$NAME.app"

INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    *) echo "usage: $0 [--install]" >&2; exit 64 ;;
  esac
done

echo "==> swift build -c release"
swift build -c release --package-path "$HERE"
BIN="$(swift build -c release --package-path "$HERE" --show-bin-path)/$PRODUCT"

echo "==> assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/$NAME"
if [[ -d "$HERE/Resources" ]]; then
  cp -R "$HERE/Resources/." "$APP/Contents/Resources/"   # fonts + their OFL licences
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

echo "==> ad-hoc codesign"
codesign --force --deep --sign - --identifier "$BUNDLE_ID" "$APP"
codesign --verify --strict "$APP"

if [[ $INSTALL -eq 1 ]]; then
  echo "==> installing to /Applications"
  rm -rf "/Applications/$NAME.app"
  cp -R "$APP" "/Applications/$NAME.app"
  echo "installed /Applications/$NAME.app"
  # An installed copy is no longer under <repo>/app/build, so record this repo as the engine
  # folder unless the user already chose one (Setup › Engine › Change… rewrites it).
  ENGINE_FILE="$HOME/Library/Application Support/$NAME/engine_path"
  REPO="$(cd "$HERE/.." && pwd)"
  if [[ ! -s "$ENGINE_FILE" && -x "$REPO/.venv/bin/python" ]]; then
    mkdir -p "$(dirname "$ENGINE_FILE")"
    echo "$REPO" > "$ENGINE_FILE"
    echo "engine_path -> $REPO"
  fi
fi
echo "done: $APP"
