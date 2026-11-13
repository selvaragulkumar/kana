import Foundation

/// UI strings in English and Japanese (docs/superpowers/specs/2026-11-13-japanese-ui-design.md).
///
/// Every user-facing string goes through `L10n.t("English text")` or, with arguments,
/// `L10n.f("Format %@", arg)`. The English text is the key, so an English UI is unchanged when a
/// table is missing. The tables are `Contents/Resources/<lang>.lproj/Kana.strings` (from
/// app/Resources, copied by build.sh). The table is named Kana, not Localizable, so SwiftUI's
/// automatic `Text("literal")` lookup never picks a language behind the override's back.
///
/// The language is the override in ••• › Language (Prefs.language) or, for "System", Japanese
/// when the first preferred language is Japanese and English otherwise. `app/check_l10n.sh`
/// checks that every key used in the sources has an en and a ja entry.
enum L10n {
    enum Choice: String, CaseIterable, Identifiable {
        case system, en, ja
        var id: String { rawValue }
    }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var choice: Choice = .system
    nonisolated(unsafe) private static var tables: [String: [String: String]] = [:]

    /// Set by Prefs (persisted) or by `--lang` for the offscreen renders (not persisted).
    static func set(_ c: Choice) {
        lock.lock(); defer { lock.unlock() }
        choice = c
    }

    /// "en" or "ja".
    static var lang: String {
        lock.lock(); let c = choice; lock.unlock()
        return resolve(c)
    }

    static var isJapanese: Bool { lang == "ja" }

    /// The language a choice shows, given the user's preferred languages (first one wins).
    static func resolve(_ c: Choice, preferred: [String] = Locale.preferredLanguages) -> String {
        switch c {
        case .en: return "en"
        case .ja: return "ja"
        case .system: return (preferred.first ?? "en").lowercased().hasPrefix("ja") ? "ja" : "en"
        }
    }

    /// The string for `key` (its English text) in the current language; the key itself if missing.
    static func t(_ key: String) -> String {
        table(lang)[key] ?? key
    }

    /// `t(key)` used as a `String(format:)` format (%@ for strings, %ld for Int, %d for Int32).
    static func f(_ key: String, _ args: CVarArg...) -> String {
        String(format: t(key), arguments: args)
    }

    private static func table(_ lang: String) -> [String: String] {
        lock.lock(); defer { lock.unlock() }
        if let t = tables[lang] { return t }
        var t: [String: String] = [:]
        if let url = Bundle.main.resourceURL?.appendingPathComponent("\(lang).lproj/Kana.strings"),
           let dict = NSDictionary(contentsOf: url) as? [String: String] {
            t = dict
        }
        tables[lang] = t
        return t
    }
}
