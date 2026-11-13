import AppKit
import CoreText
import SwiftUI

/// Tokens from design/kana-design.html. The panel is always dark.
enum Theme {
    static let name = "kana"

    static func ns(_ hex: UInt32, _ a: CGFloat = 1) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255, alpha: a)
    }
    static func c(_ hex: UInt32, _ a: Double = 1) -> Color { Color(nsColor: ns(hex, CGFloat(a))) }

    static let bg = c(0x0E0E10)
    static let surface = c(0x151518)
    static let surface2 = c(0x1C1C20)
    static let line = c(0x26262A)
    static let lineSoft = c(0x222226)
    static let lineStrong = c(0x303036)
    static let lineInput = c(0x2A2A2F)
    static let text = c(0xEDEDEF)
    static let textStrong = c(0xF2F2F4)
    static let text2 = c(0xC8C8CE)
    static let text3 = c(0xA0A0A8)
    static let text4 = c(0x8E8E94)
    static let accentNS = ns(0xFF4D2E)
    static let accent = c(0xFF4D2E)
    static let accentBg = c(0xFF4D2E, 0.12)
    static let accentLine = c(0xFF4D2E, 0.40)
    static let ok = c(0x3DD68C)
    static let alertBg = c(0xFF4D2E, 0.10)
    static let alertLine = c(0xFF4D2E, 0.38)
    static let alertTitle = c(0xFFE1DA)
    static let alertText = c(0xF2C2B8)
    static let liveText = c(0xFFD3C9)
    static let streamOff = c(0x5A5A60)

    // MARK: Fonts

    private static var descriptors: [String: CTFontDescriptor] = [:]

    /// Registers every .ttf under Contents/Resources/Fonts for this process.
    static func registerFonts() {
        guard let root = Bundle.main.resourceURL?.appendingPathComponent("Fonts"),
              let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil) else { return }
        for case let url as URL in walker where url.pathExtension.lowercased() == "ttf" {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
            if let list = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor],
               let first = list.first,
               let family = CTFontDescriptorCopyAttribute(first, kCTFontFamilyNameAttribute) as? String {
                descriptors[family] = first
            }
        }
    }

    private static let wght: UInt32 = 0x7767_6874  // 'wght'
    private static let opsz: UInt32 = 0x6F70_737A  // 'opsz'

    private static func variable(_ family: String, size: CGFloat, axes: [UInt32: CGFloat],
                                 cascade: [CTFontDescriptor] = []) -> CTFont? {
        guard let base = descriptors[family] else { return nil }
        let variation = Dictionary(uniqueKeysWithValues: axes.map { (NSNumber(value: $0.key), NSNumber(value: Double($0.value))) })
        var attrs: [CFString: Any] = [kCTFontVariationAttribute: variation]
        if !cascade.isEmpty { attrs[kCTFontCascadeListAttribute] = cascade }
        let desc = CTFontDescriptorCreateCopyWithAttributes(base, attrs as CFDictionary)
        return CTFontCreateWithFontDescriptor(desc, size, nil)
    }

    /// Noto Sans JP at a weight, used as the Japanese fallback in every UI font.
    private static func jpDescriptor(_ weight: CGFloat) -> [CTFontDescriptor] {
        guard let base = descriptors["Noto Sans JP"] else { return [] }
        let v = [NSNumber(value: wght): NSNumber(value: Double(weight))]
        return [CTFontDescriptorCreateCopyWithAttributes(base, [kCTFontVariationAttribute: v] as CFDictionary)]
    }

    /// Inter, with Noto Sans JP in the cascade so mixed English/Japanese text renders both.
    static func ui(_ size: CGFloat, _ weight: CGFloat = 400) -> Font {
        if let f = variable("Inter", size: size, axes: [wght: weight, opsz: min(max(size, 14), 32)],
                            cascade: jpDescriptor(weight)) {
            return Font(f)
        }
        return .system(size: size)
    }

    /// Noto Sans JP first (for text known to be Japanese), Inter behind it for Latin.
    static func jp(_ size: CGFloat, _ weight: CGFloat = 400) -> Font {
        if let f = variable("Noto Sans JP", size: size, axes: [wght: weight]) { return Font(f) }
        return ui(size, weight)
    }

    /// Space Grotesk 600: the wordmark only.
    static func brand(_ size: CGFloat) -> Font {
        if let f = variable("Space Grotesk", size: size, axes: [wght: 600]) { return Font(f) }
        return .system(size: size, weight: .semibold)
    }

    /// Page titles ("Setup"): the wordmark face for Latin, Noto Sans JP 600 when the title is Japanese
    /// (Space Grotesk has no Japanese glyphs). The wordmark "kana" itself always uses `brand`.
    static func heading(_ s: String, size: CGFloat) -> Font {
        isJapanese(s) ? jp(size, 600) : brand(size)
    }

    /// True when the string has kana or kanji, to pick the Japanese face for whole lines.
    static func isJapanese(_ s: String) -> Bool {
        s.unicodeScalars.contains { (0x3040...0x30FF).contains($0.value) || (0x4E00...0x9FFF).contains($0.value) }
    }

    static func text(_ s: String, size: CGFloat, weight: CGFloat = 400) -> Font {
        isJapanese(s) ? jp(size, weight) : ui(size, weight)
    }
}

// MARK: Buttons (flat, as in the handoff)

/// White filled: Start.
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .lineLimit(1)
            .fixedSize()   // a Japanese label never wraps
            .font(Theme.ui(13, 600))
            .foregroundStyle(Theme.c(0x0A0A0B))
            .padding(.horizontal, 18)
            .frame(minHeight: 36)
            .background(RoundedRectangle(cornerRadius: 10).fill(configuration.isPressed ? Theme.c(0xE6E6E8) : .white))
            .contentShape(RoundedRectangle(cornerRadius: 10))
    }
}

/// Outlined: Stop (with the white square), secondary actions.
struct GhostButtonStyle: ButtonStyle {
    var square = false
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) {
            if square { RoundedRectangle(cornerRadius: 2).fill(.white).frame(width: 9, height: 9) }
            configuration.label.lineLimit(1)
        }
        .fixedSize()
        .font(Theme.ui(13, 600))
        .foregroundStyle(.white)
        .padding(.horizontal, 14)
        .frame(minHeight: 36)
        .background(RoundedRectangle(cornerRadius: 10).strokeBorder(configuration.isPressed ? Theme.c(0x55555C) : Theme.c(0x3A3A40)))
        .contentShape(RoundedRectangle(cornerRadius: 10))
    }
}

/// Small filled: "Open Settings", "Copy", "Test key".
struct SmallButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .lineLimit(1)
            .fixedSize()
            .font(Theme.ui(12, 500))
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 8).fill(configuration.isPressed ? Theme.c(0x2C2C32) : Theme.c(0x232328)))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Theme.lineStrong))
            .opacity(enabled ? 1 : 0.45)
            .contentShape(RoundedRectangle(cornerRadius: 8))
    }
}

/// Bare icon button (refresh, dismiss, captions, more).
struct IconButtonStyle: ButtonStyle {
    var color: Color = Theme.text3
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(configuration.isPressed ? .white : color)
            .frame(minWidth: 28, minHeight: 28)
            .contentShape(Rectangle())
    }
}

// MARK: Cards

extension View {
    /// Surface card: inputs, notices, the language sides.
    func surfaceCard(radius: CGFloat = 12, border: Color = Theme.line) -> some View {
        self.background(RoundedRectangle(cornerRadius: radius).fill(Theme.surface))
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(border))
    }

    /// Red-tinted alert card.
    func alertCard() -> some View {
        self.background(RoundedRectangle(cornerRadius: 12).fill(Theme.alertBg))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Theme.alertLine))
    }
}

/// Pill chip ("Idle", "Passing through", "Live").
struct StatePill: View {
    let live: Bool
    var passing = false
    var lang = L10n.lang   // re-renders the pill when the UI language changes
    var body: some View {
        HStack(spacing: 6) {
            ZStack {
                Circle().fill(live ? Theme.accent : (passing ? Theme.ok : Theme.text4)).frame(width: 7, height: 7)
                if live { PingRing() }
            }
            Text(live ? L10n.t("Live") : (passing ? L10n.t("Pass-through") : L10n.t("Idle")))
                .lineLimit(1)
        }
        .font(Theme.ui(12))
        .foregroundStyle(live ? Theme.liveText : Theme.text2)
        .padding(.horizontal, 9)
        .padding(.vertical, 3)
        .background(Capsule().fill(live ? Theme.accentBg : Theme.surface))
        .overlay(Capsule().strokeBorder(live ? Theme.accentLine : Theme.c(0x2A2A2F)))
    }
}

/// The live dot's ping: a ring scaling .4 → 1.4 while fading out, every 1.6 s.
struct PingRing: View {
    private let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    var body: some View {
        if reduce {
            EmptyView()
        } else {
            TimelineView(.animation) { ctx in
                let p = ctx.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 1.6) / 1.6
                let e = 1 - pow(1 - p, 2)  // ease-out
                Circle()
                    .strokeBorder(Theme.accent, lineWidth: 2)
                    .frame(width: 15, height: 15)
                    .scaleEffect(0.4 + e)
                    .opacity(0.8 * (1 - e))
            }
            .frame(width: 7, height: 7)
        }
    }
}

/// Dashed badge ("fake engine", "fallback model").
struct DashedBadge: View {
    let text: String
    var body: some View {
        Text(text)
            .font(Theme.ui(11))
            .foregroundStyle(Theme.text3)
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .overlay(Capsule().strokeBorder(Theme.c(0x3A3A40), style: StrokeStyle(lineWidth: 1, dash: [3, 2])))
    }
}

/// The talk bar's level meter: five red bars, 5 → 20 pt, .9 s alternate, staggered.
struct LevelMeter: View {
    private let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    private let delays: [Double] = [0, -0.2, -0.5, -0.1, -0.7]
    var body: some View {
        TimelineView(.animation(paused: reduce)) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            HStack(alignment: .center, spacing: 3) {
                ForEach(0..<5, id: \.self) { i in
                    let phase = (t - delays[i]) / 0.9
                    let tri = abs(phase.truncatingRemainder(dividingBy: 2) - 1)  // 1→0→1
                    let e = (1 - cos(.pi * (1 - tri))) / 2
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Theme.accent)
                        .frame(width: 3, height: reduce ? 12 : 5 + 15 * e)
                }
            }
            .frame(height: 20)
        }
    }
}

/// Three pulsing dots for a translation still arriving.
struct TypingDots: View {
    private let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    var body: some View {
        TimelineView(.animation(paused: reduce)) { ctx in
            let t = ctx.date.timeIntervalSinceReferenceDate
            HStack(spacing: 3) {
                ForEach(0..<3, id: \.self) { i in
                    let p = (t - Double(i) * 0.15).truncatingRemainder(dividingBy: 1)
                    Circle().fill(Theme.accent).frame(width: 4, height: 4)
                        .opacity(reduce ? 0.8 : 0.25 + 0.75 * (1 - cos(2 * .pi * p)) / 2)
                }
            }
        }
    }
}
