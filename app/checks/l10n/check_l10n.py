"""UI string checks for app/Sources/Kana (run by app/check_l10n.sh; macOS, uses plutil).

1. Every key used as L10n.t("…") / L10n.f("…", …) has an entry in Resources/en.lproj/Kana.strings
   and Resources/ja.lproj/Kana.strings; keys are plain literals (no interpolation).
2. en values equal their keys (English is the key, so the English UI is unchanged).
3. No ja value is empty or identical to its English text, except ALLOW_SAME (product and device
   names, symbols). ja values keep the key's format specifiers (%@, %ld, %d, %.1f …) in order.
4. No unused entries in either table.
5. No bare user-facing literal in a SwiftUI/AppKit text API (Text("…"), Button("…"), .help("…"),
   menuItem("…") …): wrap it in L10n, use Text(verbatim:) for non-words, or end the line with
   `// l10n:skip`.

`--list` prints the keys in source order (one per line, JSON-escaped) and exits.
"""
import json
import pathlib
import re
import subprocess
import sys

APP = pathlib.Path(__file__).resolve().parents[2]
SOURCES = sorted((APP / "Sources" / "Kana").glob("*.swift"))
TABLES = {lang: APP / "Resources" / f"{lang}.lproj" / "Kana.strings" for lang in ("en", "ja")}

# ja may equal en for these: names that stay in Latin letters, and symbols.
ALLOW_SAME = {
    "OK",
    "powered by %@",   # brand line stays English under the ZAG wordmark
}

KEY_RE = re.compile(r'L10n\.(?:t|f)\(\s*"((?:[^"\\\n]|\\.)*)"')
BARE_RE = re.compile(
    r'(?<![\w.])(?:Text|Button|Toggle|Picker|TextField|SecureField|Link|Label|Menu)\(\s*"'
    r'|\.help\(\s*"|menuItem\(\s*"|NSMenuItem\(title:\s*"|\.(?:prompt|message|title|toolTip) = "'
    r'|alertRow\(title:\s*"|section\(\s*"')
SPEC_RE = re.compile(r"%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?(?:ld|lu|d|u|f|@|s)")


def unescape(lit: str) -> str:
    if "\\(" in lit:
        raise ValueError("interpolation in an L10n key; use L10n.f with %@")
    out, i = [], 0
    while i < len(lit):
        c = lit[i]
        if c == "\\":
            n = lit[i + 1]
            if n == "u":
                j = lit.index("}", i)
                out.append(chr(int(lit[i + 3:j], 16)))
                i = j + 1
                continue
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "'": "'", "0": "\0"}[n])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def used_keys():
    keys, errors = {}, []
    for path in SOURCES:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            for m in KEY_RE.finditer(line):
                where = f"{path.name}:{no}"
                try:
                    keys.setdefault(unescape(m.group(1)), where)
                except ValueError as e:
                    errors.append(f"{where}: {e}")
            if BARE_RE.search(line) and "l10n:skip" not in line:
                errors.append(f"{path.name}:{no}: bare UI literal, wrap it in L10n.t: {line.strip()}")
    return keys, errors


def load(path: pathlib.Path) -> dict:
    out = subprocess.run(["plutil", "-convert", "json", "-o", "-", str(path)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"{path}: not a valid .strings file: {out.stderr.strip()}")
    return json.loads(out.stdout)


def main() -> int:
    keys, errors = used_keys()
    if "--list" in sys.argv:
        for k in keys:
            print(json.dumps(k, ensure_ascii=False))
        return 0
    tables = {lang: load(p) for lang, p in TABLES.items()}
    for key, where in keys.items():
        for lang, table in tables.items():
            if key not in table:
                errors.append(f"{where}: no {lang} string for {key!r}")
        en, ja = tables["en"].get(key), tables["ja"].get(key)
        if en is not None and en != key:
            errors.append(f"{where}: en value differs from its key {key!r}: {en!r}")
        if ja is not None:
            if not ja.strip():
                errors.append(f"{where}: empty ja string for {key!r}")
            elif ja == key and key not in ALLOW_SAME:
                errors.append(f"{where}: ja string identical to English for {key!r} (add to ALLOW_SAME if intended)")
            if SPEC_RE.findall(ja) != SPEC_RE.findall(key):
                errors.append(f"{where}: ja format specifiers {SPEC_RE.findall(ja)} != en {SPEC_RE.findall(key)} for {key!r}")
    for lang, table in tables.items():
        for key in table:
            if key not in keys:
                errors.append(f"{TABLES[lang].relative_to(APP)}: unused key {key!r}")
    for e in errors:
        print("FAIL", e)
    print(f"{len(keys)} keys, en {len(tables['en'])}, ja {len(tables['ja'])}: "
          + ("ok" if not errors else f"{len(errors)} problem(s)"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
