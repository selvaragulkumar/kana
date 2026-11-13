import AppKit
import SwiftUI

/// "powered by [zag]": sits in the middle of the panel footer and at the end of Setup.
/// The wordmark is the drawn mark (brand rule: never typed), 19 pt tall, the brand minimum
/// on screen, centred on the text line. Click opens withzag.com.
struct CreditLine: View {
    static let url = URL(string: "https://withzag.com")!
    @State private var hovering = false

    private static let mark: NSImage? = {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("Brand/zag-logo-white.png") else { return nil }
        return NSImage(contentsOf: url)
    }()

    var body: some View {
        line
            .contentShape(Rectangle())
            .opacity(hovering ? 1 : 0.6)
            .onHover { hovering = $0; if $0 { NSCursor.pointingHand.push() } else { NSCursor.pop() } }
            .onTapGesture { NSWorkspace.shared.open(Self.url) }
            .help(L10n.t("Made by ZAG. Opens withzag.com."))
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text(L10n.f("powered by %@", "ZAG")))
    }

    /// The localized template around the mark ("powered by %@"), text and mark centre-aligned.
    private var line: some View {
        let parts = L10n.t("powered by %@").components(separatedBy: "%@")
        return HStack(alignment: .center, spacing: 6) {
            if let a = parts.first, !a.isEmpty { Text(verbatim: a.trimmingCharacters(in: .whitespaces)) }
            if let m = Self.mark {
                Image(nsImage: m).resizable().interpolation(.high).scaledToFit().frame(height: 16)
            } else {
                Text(verbatim: "zag")
            }
            if parts.count > 1, !parts[1].isEmpty { Text(verbatim: parts[1].trimmingCharacters(in: .whitespaces)) }
        }
        .font(Theme.ui(11))
        .foregroundStyle(Theme.text4)
    }
}
