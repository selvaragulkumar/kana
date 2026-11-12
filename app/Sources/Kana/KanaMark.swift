import AppKit
import SwiftUI

/// The six mark states from design/kana-design.html.
enum MarkState: String, CaseIterable {
    case idle, connecting, listening, talking, translating, error
}

/// CSS `cubic-bezier(x1,y1,x2,y2)` evaluated at x (solved for t by Newton + bisection).
struct CubicBezier {
    let x1, y1, x2, y2: Double
    static let easeInOut = CubicBezier(x1: 0.42, y1: 0, x2: 0.58, y2: 1)
    static let trace = CubicBezier(x1: 0.6, y1: 0, x2: 0.3, y2: 1)

    private func bez(_ t: Double, _ a: Double, _ b: Double) -> Double {
        let u = 1 - t
        return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t
    }

    func callAsFunction(_ x: Double) -> Double {
        if x <= 0 { return 0 }
        if x >= 1 { return 1 }
        var lo = 0.0, hi = 1.0, t = x
        for _ in 0..<24 {
            let v = bez(t, x1, x2)
            if abs(v - x) < 1e-5 { break }
            if v < x { lo = t } else { hi = t }
            t = (lo + hi) / 2
        }
        return bez(t, y1, y2)
    }
}

/// Keyframe track: (offset 0...1, value), with an easing applied per segment, as CSS does.
struct Keyframes {
    let frames: [(Double, Double)]
    let ease: CubicBezier

    func value(at p: Double) -> Double {
        guard let first = frames.first, let last = frames.last else { return 0 }
        if p <= first.0 { return first.1 }
        if p >= last.0 { return last.1 }
        for i in 0..<(frames.count - 1) where p >= frames[i].0 && p <= frames[i + 1].0 {
            let (a, va) = frames[i], (b, vb) = frames[i + 1]
            let local = b > a ? (p - a) / (b - a) : 1
            return va + (vb - va) * ease(local)
        }
        return last.1
    }
}

/// Geometry and motion of the bracket mark in its 200 × 200 viewBox.
enum MarkGeometry {
    static let b1: [CGPoint] = [CGPoint(x: 44, y: 128), CGPoint(x: 44, y: 44), CGPoint(x: 128, y: 44)]
    static let b2: [CGPoint] = [CGPoint(x: 156, y: 72), CGPoint(x: 156, y: 156), CGPoint(x: 72, y: 156)]
    static let dash: Double = 168   // each bracket's length (84 + 84)

    /// Stroke width in viewBox units: 20, thickened to 26 below 32 pt.
    static func stroke(for size: CGFloat) -> CGFloat { size < 32 ? 26 : 20 }

    static func path(_ pts: [CGPoint]) -> Path {
        var p = Path()
        p.move(to: pts[0])
        for q in pts.dropFirst() { p.addLine(to: q) }
        return p
    }

    // translating: stroke-dashoffset keyframes, 1.8 s, cubic-bezier(.6,0,.3,1) per segment
    static let trace1 = Keyframes(frames: [(0, 168), (0.35, 0), (0.70, 0), (1, -168)], ease: .trace)
    static let trace2 = Keyframes(frames: [(0, 168), (0.20, 168), (0.55, 0), (0.85, 0), (1, -168)], ease: .trace)
    // error: translateX keyframes, .5 s, once
    static let shake = Keyframes(frames: [(0, 0), (0.2, -10), (0.4, 9), (0.6, -6), (0.8, 3), (1, 0)], ease: .easeInOut)

    /// Frame of the mark at time `t` seconds after entering `state`.
    struct Frame {
        var rotation: Double = 0          // degrees, whole mark
        var off1 = CGSize.zero, off2 = CGSize.zero
        var trim1: ClosedRange<Double> = 0...1, trim2: ClosedRange<Double> = 0...1
        var alpha1: Double = 1, alpha2: Double = 1
    }

    static func frame(_ state: MarkState, t: Double, reduceMotion: Bool) -> Frame {
        var f = Frame()
        if state == .error { f.alpha1 = 0.3 }
        if reduceMotion { return f }   // colours still signal the state; no motion
        switch state {
        case .idle:
            break
        case .connecting:
            // rotate(360deg) over 1.6 s with steps(4, end): quarter turns every 0.4 s
            f.rotation = floor((t.truncatingRemainder(dividingBy: 1.6)) / 0.4) * 90
        case .listening:
            // 2.4 s ease-in-out breathe: b1 to (-8,-8), b2 to (8,8) at 50 %
            let p = t.truncatingRemainder(dividingBy: 2.4) / 2.4
            let tri = p < 0.5 ? p * 2 : (1 - p) * 2
            let e = CubicBezier.easeInOut(tri)
            f.off1 = CGSize(width: -8 * e, height: -8 * e)
            f.off2 = CGSize(width: 8 * e, height: 8 * e)
        case .talking:
            // .46 s ease-in-out, alternate: b1 to (9,9), b2 to (-9,-9)
            let cycle = t.truncatingRemainder(dividingBy: 0.92) / 0.46
            let e = CubicBezier.easeInOut(cycle <= 1 ? cycle : 2 - cycle)
            f.off1 = CGSize(width: 9 * e, height: 9 * e)
            f.off2 = CGSize(width: -9 * e, height: -9 * e)
        case .translating:
            let p = t.truncatingRemainder(dividingBy: 1.8) / 1.8
            f.trim1 = trim(offset: trace1.value(at: p))
            f.trim2 = trim(offset: trace2.value(at: p))
        case .error:
            let p = min(t / 0.5, 1)
            f.off2 = CGSize(width: shake.value(at: p), height: 0)
        }
        return f
    }

    /// SVG dasharray 168 / dashoffset o on a 168-long path, as a visible fraction range.
    static func trim(offset o: Double) -> ClosedRange<Double> {
        if o >= 0 { return 0...max(0, 1 - o / dash) }
        return min(1, -o / dash)...1
    }

    /// Draws the mark into a context sized `size`, in the given colours.
    static func draw(in ctx: inout GraphicsContext, size: CGFloat, frame f: Frame,
                     color1: Color, color2: Color) {
        let s = size / 200
        ctx.translateBy(x: size / 2, y: size / 2)
        ctx.rotate(by: .degrees(f.rotation))
        ctx.translateBy(x: -size / 2, y: -size / 2)
        ctx.scaleBy(x: s, y: s)
        let style = StrokeStyle(lineWidth: stroke(for: size), lineCap: .square, lineJoin: .miter)
        for (pts, off, trim, color, alpha) in [(b1, f.off1, f.trim1, color1, f.alpha1), (b2, f.off2, f.trim2, color2, f.alpha2)] {
            guard trim.upperBound > trim.lowerBound else { continue }
            let p = path(pts).trimmedPath(from: trim.lowerBound, to: trim.upperBound)
                .offsetBy(dx: off.width, dy: off.height)
            ctx.stroke(p, with: .color(color.opacity(alpha)), style: style)
        }
    }
}

/// The animated mark. `state` changes restart the state's timeline (so error shakes once).
struct KanaMark: View {
    let state: MarkState
    var size: CGFloat = 24
    var color1: Color = .white
    var color2: Color = Theme.accent
    /// For rendering stills: a fixed time into the state instead of the live clock.
    var fixedTime: Double?

    @State private var since = Date()
    private let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

    var body: some View {
        let animated = fixedTime == nil && !reduce && state != .idle
        TimelineView(.animation(paused: !animated)) { ctx in
            let t = fixedTime ?? ctx.date.timeIntervalSince(since)
            let f = MarkGeometry.frame(state, t: t, reduceMotion: reduce && fixedTime == nil)
            Canvas { gc, _ in
                var g = gc
                MarkGeometry.draw(in: &g, size: size, frame: f, color1: color1, color2: color2)
            }
            .frame(width: size, height: size)
            .animation(.easeOut(duration: 0.3), value: f.alpha1)
        }
        .onChange(of: state) { _, _ in since = Date() }
        .accessibilityLabel("kana, \(state.rawValue)")
    }
}
