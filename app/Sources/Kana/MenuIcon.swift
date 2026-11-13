import AppKit

/// Menu-bar icon from design/kana-menubar-template.svg: static brackets at stroke 26 in a
/// 200 viewBox, 18 pt. A template image (black + alpha, the system tints it); while talking it
/// is drawn non-template so the right bracket can be red.
enum MenuIcon {
    private static let size = NSSize(width: 18, height: 18)

    static func image(talking: Bool) -> NSImage {
        let img = NSImage(size: size, flipped: true) { rect in
            let s = rect.width / 200
            func bracket(_ pts: [CGPoint], _ color: NSColor) {
                let p = NSBezierPath()
                p.move(to: NSPoint(x: pts[0].x * s, y: pts[0].y * s))
                for q in pts.dropFirst() { p.line(to: NSPoint(x: q.x * s, y: q.y * s)) }
                p.lineWidth = 26 * s
                p.lineCapStyle = .square
                p.lineJoinStyle = .miter
                color.setStroke()
                p.stroke()
            }
            if talking {
                let dark = NSAppearance.currentDrawing().bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
                bracket(MarkGeometry.b1, dark ? .white : .black)
                bracket(MarkGeometry.b2, Theme.accentNS)
            } else {
                bracket(MarkGeometry.b1, .black)
                bracket(MarkGeometry.b2, NSColor.black.withAlphaComponent(0.6))
            }
            return true
        }
        img.isTemplate = !talking
        img.accessibilityDescription = talking ? L10n.f("kana, %@", MarkState.talking.spoken) : Theme.name
        return img
    }
}
