#!/bin/bash
# Builds the downloadable DMG: kana.app with its own Python engine, plus an Applications link.
#   app/release.sh                 -> dist/kana-<version>.dmg        (Apple silicon)
#   app/release.sh --arch x86_64   -> dist/kana-<version>-intel.dmg  (Intel; pip runs under Rosetta)
#   app/release.sh --arch all      -> both
# Signing (no credentials are created here):
#   KANA_SIGN_IDENTITY     identity for the app and the DMG ("-" = ad-hoc). Default: the local
#                          "kana Local Signing" certificate if present, else ad-hoc.
#   KANA_NOTARY_PROFILE    a notarytool keychain profile (xcrun notarytool store-credentials).
#                          With a "Developer ID Application" identity, the build uses the
#                          hardened runtime and the DMG is notarised and stapled.
# Uses hdiutil, codesign and xcrun only. Writes dist/checksums.txt (SHA-256).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DIST="$REPO/dist"
VERSION="$("$HERE/build.sh" --print-version)"

ARCHES=(arm64)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      case "${2:-}" in
        all) ARCHES=(arm64 x86_64) ;;
        arm64|x86_64) ARCHES=("$2") ;;
        *) echo "unknown arch: ${2:-}" >&2; exit 64 ;;
      esac
      shift 2 ;;
    *) echo "usage: $0 [--arch arm64|x86_64|all]" >&2; exit 64 ;;
  esac
done

IDENTITY="${KANA_SIGN_IDENTITY:-}"
if [[ -z "$IDENTITY" ]] && security find-identity -p codesigning 2>/dev/null | grep -q '"kana Local Signing"'; then
  IDENTITY="kana Local Signing"
fi
[[ -z "$IDENTITY" ]] && IDENTITY="-"
export KANA_SIGN_IDENTITY="$IDENTITY"

NOTARIZE=0
if [[ -n "${KANA_NOTARY_PROFILE:-}" && "$IDENTITY" == "Developer ID Application:"* ]]; then
  NOTARIZE=1
  export KANA_HARDENED=1
elif [[ -n "${KANA_NOTARY_PROFILE:-}" ]]; then
  echo "KANA_NOTARY_PROFILE is set but KANA_SIGN_IDENTITY is not a \"Developer ID Application: …\" identity; not notarising." >&2
fi

mkdir -p "$DIST"
MADE=()
for ARCH in "${ARCHES[@]}"; do
  SUFFIX=""; [[ "$ARCH" == x86_64 ]] && SUFFIX="-intel"
  DMG="$DIST/kana-$VERSION$SUFFIX.dmg"
  echo "=== kana $VERSION for $ARCH ==="
  "$HERE/build.sh" --bundle-engine --arch "$ARCH"

  STAGE="$(mktemp -d "${TMPDIR:-/tmp}/kana-dmg.XXXXXX")"
  ditto "$HERE/build/kana.app" "$STAGE/kana.app"
  ln -s /Applications "$STAGE/Applications"
  codesign --verify --strict --deep "$STAGE/kana.app"

  echo "==> hdiutil create $DMG"
  rm -f "$DMG"
  hdiutil create -quiet -volname "kana $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO \
    -imagekey zlib-level=9 "$DMG"
  rm -rf "$STAGE"
  if [[ "$IDENTITY" != "-" ]]; then
    codesign --force --sign "$IDENTITY" ${KANA_HARDENED:+--timestamp} "$DMG"
  fi
  hdiutil verify -quiet "$DMG"

  if [[ $NOTARIZE -eq 1 ]]; then
    echo "==> notarising (xcrun notarytool, profile $KANA_NOTARY_PROFILE)"
    xcrun notarytool submit "$DMG" --keychain-profile "$KANA_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
    spctl --assess --type open --context context:primary-signature -v "$DMG" || true
  fi
  MADE+=("$DMG")
done

(cd "$DIST" && shasum -a 256 kana-"$VERSION"*.dmg > checksums.txt)
echo
for d in "${MADE[@]}"; do du -h "$d" | awk '{print "built " $2 " (" $1 ")"}'; done
echo "checksums: $DIST/checksums.txt"
if [[ $NOTARIZE -eq 0 ]]; then
  cat <<'NOTE'

Not notarised (no Developer ID identity + KANA_NOTARY_PROFILE). macOS will block the first
open of a downloaded copy: right-click kana.app > Open (macOS 14), or System Settings >
Privacy & Security > Open Anyway (macOS 15 and later). Say so next to the download link.
NOTE
fi
