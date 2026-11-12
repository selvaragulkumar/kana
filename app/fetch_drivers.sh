#!/bin/bash
# Downloads Existential Audio's BlackHole 2ch and 16ch installers into app/build/cache, checks
# them against the SHA-256 in the Homebrew casks and the vendor's signature, and copies them
# with BlackHole's licence and a source link into <dest>.
#   app/fetch_drivers.sh <dest>
# Used by build.sh only with KANA_BUNDLE_DRIVERS=1. Read app/drivers/README.md first: the
# compiled installers are not GPL, so ship them only with Existential Audio's permission.
# Keep the version and sums in step with app/Sources/Kana/DriverInstaller.swift.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?usage: $0 <dest>}"
CACHE="$HERE/build/cache"
VERSION="0.7.1"
SIGNER="Developer ID Installer: Existential Audio Inc. (Q5C99V536K)"
PKGS=(
  "BlackHole2ch-$VERSION.pkg 57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"
  "BlackHole16ch-$VERSION.pkg 57254e2f76cd40db7f3f715238b1a2cb2bd08819d38abf4087f2944f71a3641a"
)

mkdir -p "$CACHE" "$DEST"
for entry in "${PKGS[@]}"; do
  file="${entry%% *}"; sum="${entry##* }"
  if [[ ! -f "$CACHE/$file" ]]; then
    echo "==> downloading $file"
    curl -fsSL --retry 3 -o "$CACHE/$file.part" "https://existential.audio/downloads/$file"
    mv "$CACHE/$file.part" "$CACHE/$file"
  fi
  got="$(shasum -a 256 "$CACHE/$file" | cut -d' ' -f1)"
  if [[ "$got" != "$sum" ]]; then
    echo "SHA-256 mismatch for $file: got $got, want $sum (Homebrew cask)" >&2
    rm -f "$CACHE/$file"; exit 1
  fi
  if ! pkgutil --check-signature "$CACHE/$file" | grep -qF "1. $SIGNER"; then
    echo "$file is not signed by $SIGNER" >&2; exit 1
  fi
  cp "$CACHE/$file" "$DEST/$file"
  echo "    $file ok"
done
cp "$HERE/drivers/BlackHole-LICENSE.txt" "$DEST/LICENSE.txt"
cat > "$DEST/SOURCE.txt" <<EOF
BlackHole $VERSION by Existential Audio Inc., unmodified official installers.
Source code (GPL-3.0): https://github.com/ExistentialAudio/BlackHole/tree/v$VERSION
Installers: https://existential.audio/downloads/BlackHole2ch-$VERSION.pkg
            https://existential.audio/downloads/BlackHole16ch-$VERSION.pkg
EOF
