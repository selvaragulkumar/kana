# BlackHole drivers

kana routes Meet's audio through two virtual devices, BlackHole 2ch and BlackHole 16ch, made
by Existential Audio Inc. Setup's **Install audio drivers** button installs both with one
password prompt (`app/Sources/Kana/DriverInstaller.swift`).

## Where the installers come from

By default the app **downloads** the official installers when the user presses the button,
from the same URLs the Homebrew casks `blackhole-2ch` and `blackhole-16ch` use:

| File | SHA-256 (from the cask) |
|---|---|
| `https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg` | `57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf` |
| `https://existential.audio/downloads/BlackHole16ch-0.7.1.pkg` | `57254e2f76cd40db7f3f715238b1a2cb2bd08819d38abf4087f2944f71a3641a` |

Each file must match its sum and be signed by
`Developer ID Installer: Existential Audio Inc. (Q5C99V536K)`; the admin step checks the sum
again after copying the files somewhere only root can write.

## Why they are not inside the DMG

BlackHole's [LICENSE](BlackHole-LICENSE.txt) (v0.7.1) says the *source code* is GPL-3.0, but
"official compiled BlackHole binaries and installers distributed by Existential Audio Inc. are
… All rights reserved", and its README asks non-GPL apps that integrate BlackHole to contact
Existential Audio for a licence. kana is Apache-2.0, so it does not redistribute the official
installers. Downloading them on the user's request, like Homebrew does, is not redistribution.

If Existential Audio gives permission, `KANA_BUNDLE_DRIVERS=1 app/release.sh` puts both pkgs
into `kana.app/Contents/Resources/drivers/` with this licence and a source link
(`app/fetch_drivers.sh`); the app then installs from those copies and makes no download.

## Updating the version

Change the version and both sums in `DriverInstaller.swift`, `fetch_drivers.sh` and this file,
taking the sums from `https://formulae.brew.sh/api/cask/blackhole-2ch.json` and
`…/blackhole-16ch.json`. Refresh `BlackHole-LICENSE.txt` from the new tag.
