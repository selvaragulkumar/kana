#!/bin/bash
# Compiles TalkKeyLogic.swift alone with app/checks/talk_key/main.swift and runs the checks.
# Command Line Tools only; no window, no event tap, nothing installed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
swiftc -warnings-as-errors "$HERE/Sources/Kana/TalkKeyLogic.swift" "$HERE/checks/talk_key/main.swift" -o "$OUT/check"
"$OUT/check"
