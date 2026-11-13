import AppKit
import SwiftUI

/// "a product of [zag]": one quiet line under the panel footer and at the end of Setup.
/// The wordmark is the drawn mark (brand rule: never typed), 19 pt tall, the brand minimum
/// on screen, with clear space around it. Click opens withzag.com.
struct CreditLine: View {
    static let url = URL(string: "https://withzag.com")!
    @State private var hovering = false

    private static let mark: NSImage? = {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent("Brand/zag-logo-white.png"),
              let img = NSImage(contentsOf: url) else { return nil }
        img.size = NSSize(width: 19 * img.size.width / img.size.height, height: 19)
        return img
    }()

    var body: some View {
        HStack {
            Spacer(minLength: 0)
            line
                .font(Theme.ui(11))
                .foregroundStyle(Theme.text4)
                .opacity(hovering ? 1 : 0.6)
                .padding(.vertical, 4)
                .contentShape(Rectangle())
                .onHover { hovering = $0; if $0 { NSCursor.pointingHand.push() } else { NSCursor.pop() } }
                .onTapGesture { NSWorkspace.shared.open(Self.url) }
                .help(L10n.t("Made by ZAG. Opens withzag.com."))
                .accessibilityLabel(Text(L10n.f("a product of %@", "ZAG")))
        }
        .padding(.top, -10)      // sit close under the footer rule
        .padding(.bottom, -10)   // and use part of the panel's own inset
    }

    /// The localized template around the mark: "a product of %@" / "%@ のプロダクト".
    private var line: Text {
        let template = L10n.t("a product of %@")
        let parts = template.components(separatedBy: "%@")
        let mark: Text = Self.mark.map { Text(Image(nsImage: $0)).baselineOffset(-4) } ?? Text(verbatim: "zag")
        return Text(verbatim: parts.first ?? "") + mark + Text(verbatim: parts.count > 1 ? parts[1] : "")
    }
}
