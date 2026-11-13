import Foundation

// Checks for L10n.swift, compiled alone by app/check_l10n.sh with the en/ja tables copied next
// to the binary (Bundle.main.resourceURL of a command-line tool is its folder).

var failures = 0
func expect(_ ok: Bool, _ what: String) {
    if !ok { failures += 1; print("FAIL", what) }
}

// Language resolution: System follows the first preferred language only.
expect(L10n.resolve(.system, preferred: ["ja-JP", "en-US"]) == "ja", "system, ja first -> ja")
expect(L10n.resolve(.system, preferred: ["ja"]) == "ja", "system, ja -> ja")
expect(L10n.resolve(.system, preferred: ["en-US", "ja-JP"]) == "en", "system, en first -> en")
expect(L10n.resolve(.system, preferred: ["fr-FR", "ja-JP"]) == "en", "system, other first -> en")
expect(L10n.resolve(.system, preferred: []) == "en", "system, none -> en")
expect(L10n.resolve(.en, preferred: ["ja-JP"]) == "en", "override en beats a Japanese system")
expect(L10n.resolve(.ja, preferred: ["en-US"]) == "ja", "override ja beats an English system")

// Lookups through the real tables.
L10n.set(.ja)
expect(L10n.lang == "ja" && L10n.isJapanese, "set(.ja) -> lang ja")
expect(L10n.t("Start") == "開始", "ja Start -> 開始, got \(L10n.t("Start"))")
expect(L10n.t("Setup…") == "セットアップ…", "ja Setup… -> セットアップ…")
expect(L10n.f("Talking · %@ → %@", "English", "日本語") == "話し中 · English → 日本語", "ja format with two %@")
expect(L10n.f("Step %ld of 3 · %@", 2, "x") == "ステップ 2/3 · x", "ja format with %ld")
expect(L10n.t("no such key, falls back") == "no such key, falls back", "missing key -> the key itself")

L10n.set(.en)
expect(L10n.lang == "en" && !L10n.isJapanese, "set(.en) -> lang en")
expect(L10n.t("Start") == "Start", "en Start -> Start")
expect(L10n.f("Silence skipped (not sent): IN %.0f s · OUT %.0f s, about $%.3f saved", 12.0, 3.0, 0.00131)
       == "Silence skipped (not sent): IN 12 s · OUT 3 s, about $0.001 saved", "en format with doubles")

if failures > 0 {
    print("\(failures) L10n check(s) failed")
    exit(1)
}
print("L10n: resolution and lookups ok")
