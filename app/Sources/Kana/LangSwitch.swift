import SwiftUI

/// EN | 日本語, the visible UI-language switch (header of the panel and of Setup). Sets the
/// override in Prefs, so it applies live; ••• › Language still offers "System".
struct LangSwitch: View {
    @EnvironmentObject private var prefs: Prefs

    var body: some View {
        HStack(spacing: 0) {
            segment("EN", .en)
            segment("日本語", .ja)
        }
        .background(Capsule().fill(Theme.surface))
        .overlay(Capsule().strokeBorder(Theme.c(0x2A2A2F)))
        .help(L10n.t("Language"))
    }

    private func segment(_ label: String, _ choice: L10n.Choice) -> some View {
        _ = prefs.language   // observe the pref; the effective language also covers --lang renders
        let on = L10n.lang == choice.rawValue
        return Button { prefs.language = choice } label: {
            Text(verbatim: label)
                .font(Theme.ui(11, on ? 600 : 500))
                .foregroundStyle(on ? Theme.text : Theme.text4)
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(Capsule().fill(on ? Theme.c(0x2A2A2F) : .clear))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(verbatim: label))
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}

/// First-run card at the top of Setup: pick the language before reading the steps.
/// Shown until a language has been chosen once (the switch above also counts).
struct LanguageChoiceCard: View {
    @EnvironmentObject private var prefs: Prefs

    static var needed: Bool { UserDefaults.standard.string(forKey: "uiLanguage") == nil }

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: "Language · 言語")
                    .font(Theme.ui(13, 600))
                    .foregroundStyle(Theme.text)
                Text(verbatim: "Choose the language for these steps. · この説明の言語を選んでください。")
                    .font(Theme.ui(11))
                    .foregroundStyle(Theme.text3)
            }
            Spacer(minLength: 8)
            Button { prefs.language = .en } label: { Text(verbatim: "English") }
                .buttonStyle(SmallButtonStyle())
            Button { prefs.language = .ja } label: { Text(verbatim: "日本語") }
                .buttonStyle(SmallButtonStyle())
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surface))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.c(0x2A2A2F)))
    }
}
