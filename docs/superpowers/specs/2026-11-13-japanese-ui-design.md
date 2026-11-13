# Japanese UI (2026-11-13)

The owner wants the whole app available in Japanese: panel, mini bar, captions hint, the •••
menu, the menu-bar menu, Setup, tooltips, error headings and the errors the app itself writes.
English stays exactly as it was.

## Mechanism

- **`L10n`** (`app/Sources/Kana/L10n.swift`): `L10n.t("English text")` and, with arguments,
  `L10n.f("Format %@", x)` (`String(format:)` specifiers: `%@`, `%ld` for Int, `%d` for Int32,
  `%.1f`). The English text is the key, so a missing table or entry shows English.
- **Tables**: `app/Resources/en.lproj/Kana.strings` (every value equals its key) and
  `app/Resources/ja.lproj/Kana.strings`, copied into `Contents/Resources/` by `build.sh` like the
  fonts. `L10n` reads `<lang>.lproj/Kana.strings` from `Bundle.main.resourceURL` itself and caches
  it per language.
- **Why not SwiftPM resources and `Bundle.module`.** `build.sh` assembles the bundle by hand
  (Command Line Tools only, no Xcode). SwiftPM would emit a `Kana_Kana.bundle` that the generated
  `Bundle.module` accessor looks for next to the executable or at the `.app` root, where it breaks
  the code signature (unsealed contents) and crashes when absent. The `app/Resources` folder is
  already copied into `Contents/Resources`, so the `.lproj` folders ride along with no new build
  step.
- **Why the table is `Kana`, not `Localizable`.** SwiftUI looks up `Text("literal")` in
  `Localizable.strings` of `Bundle.main` by the system language. With its own table name nothing
  is translated behind the override's back; `L10n` returns `String`s and `Text(String)` is
  verbatim.
- `Info.plist` gains `CFBundleDevelopmentRegion` en and `CFBundleLocalizations` [en, ja], and
  `ja.lproj/InfoPlist.strings` translates `NSMicrophoneUsageDescription`, so the parts macOS draws
  (the microphone prompt, open-panel buttons, text-field menus) follow the macOS language.

## Language choice and override

- `Prefs.language` (UserDefaults `uiLanguage`): `system` (default), `en`, `ja`.
- System: Japanese when the first entry of `Locale.preferredLanguages` starts with `ja`, English
  otherwise (a per-app language set in System Settings › General › Language & Region counts,
  because it changes that list).
- Override: ••• › **Language** (`言語 (Language)` in Japanese, so it can be found from either side)
  with System / English / 日本語, and the same submenu in the menu-bar right-click menu. The names
  "English" and "日本語" are never translated.
- **Live.** Setting the pref calls `L10n.set`; the panel, mini bar and Setup observe `Prefs` and
  re-render. Views that do not observe it (`StatePill`, `TranscriptRowView`) carry
  `var lang = L10n.lang` so a parent re-render after a switch reaches them. The menu-bar menu is
  built on each right-click; the caption strip re-renders every 0.2 s. No restart is needed.
- What does not switch live: text already stored as state (a shown error, a Setup key-test or
  install message, a loopback result) keeps the language it was written in until it is replaced.
  The macOS-drawn parts above follow the macOS language, not the override.
- `--lang en|ja|system` (or `KANA_LANG`) sets the language for one run without saving it; used by
  `kana --render-setup <dir> --lang ja` and `kana --render-intro <dir> --lang ja`.

## What stays English (or Latin)

- The wordmark "kana" (Space Grotesk) and product, model and device names: kana, BlackHole 2ch /
  16ch, Google Meet / Meet, Gemini, OpenAI, Existential Audio, AI Studio, model ids.
- IN / OUT labels, key symbols (⌥, ⌘, fn, ⌃⌥Space), units and numbers ("1.8 s", "$0.31", "≈¥47").
- Language names in the presets (each in its own language) and BCP-47 codes.
- Text produced by the Python engine (its `error` events, stderr tails) and by macOS
  (`localizedDescription` of system errors follows macOS).
- Developer-only output: `--driver-install-dry-run` prints, the mark stills' labels, borderless
  window titles nobody sees.

## Typography and layout

- `Theme.ui` is Inter with Noto Sans JP in its cascade, so Japanese labels get JP glyphs.
  `Theme.heading` (new) picks Noto Sans JP 600 for a Japanese page title (Setup → セットアップ)
  and Space Grotesk for Latin; the wordmark keeps `Theme.brand`.
- Primary, ghost and small button styles are `.lineLimit(1).fixedSize()` so a Japanese label never
  wraps (the pattern from "Panel header: Start never wraps").
- The footer's live stream label is `L10n.f("%@ live%@", name, latency)`: English "IN live · 1.8
  s", Japanese "IN · 1.8 s" (the green dot says live), because "接続中" did not fit beside both
  delays.

## Copy rules

です・ます for sentences, short noun phrases for buttons and menu items, the terms of
README.ja.md (トークキー, トークバー, パススルー, 字幕, アクセシビリティ, マイク, イヤホン,
ドライバー), Start = 開始, Stop = 停止, Setup = セットアップ, no 様. README.ja.md has a table of the
English labels it quotes and their Japanese form.

## Test seams

- `app/check_l10n.sh`: (1) `app/checks/l10n/check_l10n.py` extracts every `L10n.t` / `L10n.f` key
  from the sources and fails when a key lacks an en or ja entry, an en value differs from its key,
  a ja value is empty or identical to English (allowlist: "OK"), format specifiers differ, an
  entry is unused, or a bare literal is passed to a UI text API (`Text("…")`, `Button("…")`,
  `.help("…")`, `menuItem("…")` …; `Text(verbatim:)` or `// l10n:skip` for non-words).
  (2) compiles `L10n.swift` alone with `app/checks/l10n/main.swift` and checks language resolution
  (`L10n.resolve(_:preferred:)`) and real lookups through the copied `.lproj` tables.
- Offscreen renders in both languages: `docs/images/panel-live-ja.png`, `panel-idle-ja.png`,
  `setup-ja.png` come from `--render-intro` / `--render-setup` with `--lang ja`.
