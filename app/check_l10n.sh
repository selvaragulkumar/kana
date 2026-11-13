#!/bin/bash
# UI string checks. Command Line Tools only; no window, nothing installed.
#  1. app/checks/l10n/check_l10n.py: every L10n key in app/Sources/Kana has an en and a ja string,
#     no ja string is empty or the same as the English (allowlist inside), format specifiers
#     match, no unused entries, no bare UI literal left outside L10n.
#  2. Compiles L10n.swift alone with app/checks/l10n/main.swift and runs it against the real
#     tables: language resolution (system / en / ja) and lookups through the .lproj loader.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 "$HERE/checks/l10n/check_l10n.py"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
cp -R "$HERE/Resources/en.lproj" "$HERE/Resources/ja.lproj" "$OUT/"   # next to the binary = Bundle.main.resourceURL
swiftc -warnings-as-errors "$HERE/Sources/Kana/L10n.swift" "$HERE/checks/l10n/main.swift" -o "$OUT/check"
"$OUT/check"
