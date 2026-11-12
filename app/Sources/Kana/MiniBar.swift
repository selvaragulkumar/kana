import AppKit
import QuartzCore
import SwiftUI

/// The minimized panel: a 380 × 64 floating bar with the mark, the latest inbound translation
/// (the previous one above it), IN/OUT dots and a talk glyph. Always on top, on all Spaces,
/// hidden from screen share like the panel, draggable by its background, position persisted.
@MainActor
final class MiniBarController: NSObject, NSWindowDelegate {
    static let size = NSSize(width: 380, height: 64)
    let window: NSPanel
    private let hover = CaptionHover()

    init(engine: EngineProcess, actions: AppActions) {
        window = NSPanel(contentRect: NSRect(origin: .zero, size: Self.size),
                         styleMask: [.borderless, .nonactivatingPanel],
                         backing: .buffered, defer: false)
        super.init()
        window.level = .floating
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.hidesOnDeactivate = false
        window.isReleasedWhenClosed = false
        window.becomesKeyOnlyIfNeeded = true
        window.title = "\(Theme.name) bar"
        window.delegate = self
        let view = MiniBarView(onExpand: { actions.expand() }, onClose: { actions.closeBar() })
            .environmentObject(engine)
            .environmentObject(hover)
        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: Self.size)
        window.contentView = host
        WindowPrivacy.apply(window)
    }

    /// The saved spot if it is still on a screen; otherwise nil (the caller picks one).
    var savedFrame: NSRect? {
        guard let s = UserDefaults.standard.string(forKey: "miniOrigin") else { return nil }
        let r = NSRect(origin: NSPointFromString(s), size: Self.size)
        return NSScreen.screens.contains { $0.visibleFrame.intersects(r) } ? r : nil
    }

    func windowDidMove(_ notification: Notification) {
        UserDefaults.standard.set(NSStringFromPoint(window.frame.origin), forKey: "miniOrigin")
    }

    func show(at frame: NSRect, fadeIn: Bool) {
        WindowPrivacy.apply(window)
        window.setFrame(frame, display: true)
        UserDefaults.standard.set(NSStringFromPoint(frame.origin), forKey: "miniOrigin")
        window.alphaValue = fadeIn ? 0 : 1
        window.orderFrontRegardless()
        if fadeIn {
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.12
                window.animator().alphaValue = 1
            }
        }
        hover.inside = false
    }

    func hide() { window.orderOut(nil) }
}

/// Bar content. The mark expands the panel; a double-click anywhere on the bar does too.
struct MiniBarView: View {
    @EnvironmentObject private var engine: EngineProcess
    @EnvironmentObject private var hover: CaptionHover
    var onExpand: () -> Void
    var onClose: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onExpand) {
                KanaMark(state: engine.markState, size: 28)
            }
            .buttonStyle(.plain)
            .help("Expand")

            lines
                .frame(maxWidth: .infinity, alignment: .leading)
                .allowsHitTesting(false)

            if hover.inside {
                Button(action: onExpand) {
                    Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
                .help("Expand")
                Button(action: onClose) {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
                .help("Close")
            } else {
                status
            }
        }
        .padding(.horizontal, 14)
        .frame(width: MiniBarController.size.width, height: MiniBarController.size.height)
        .background(BarDragArea(onDoubleClick: onExpand))
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.bg))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.line).allowsHitTesting(false))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .environment(\.colorScheme, .dark)
        .onHover { hover.inside = $0 }
    }

    /// Latest inbound translation (17 pt) with the previous one above it (12 pt, 60 %);
    /// a new line slides up into place.
    private var lines: some View {
        let inbound = engine.rows.filter { $0.dir == .inbound && !$0.dst.isEmpty }
        let latest = inbound.last
        let previous = inbound.dropLast().last
        return VStack(alignment: .leading, spacing: 1) {
            if let previous {
                Text(previous.dst)
                    .font(Theme.text(previous.dst, size: 12))
                    .foregroundStyle(Theme.text4)
                    .opacity(0.6)
                    .lineLimit(1)
                    .id("p-\(previous.id)")
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let latest {
                Text(latest.dst)
                    .font(Theme.text(latest.dst, size: 17, weight: 500))
                    .foregroundStyle(Theme.textStrong)
                    .lineLimit(1)
                    .truncationMode(.head)
                    .id("l-\(latest.id)")
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else {
                Text(engine.running ? "Listening…" : "Idle. Expand to start.")
                    .font(Theme.ui(13))
                    .foregroundStyle(Theme.text4)
            }
        }
        .clipped()
        .animation(.easeOut(duration: 0.25), value: latest?.id)
    }

    private var status: some View {
        HStack(spacing: 10) {
            HStack(spacing: 4) {
                dot(engine.inState == .connected)
                dot(engine.outState == .connected)
            }
            .help(dotsTooltip)
            Image(systemName: engine.talking ? "mic.fill" : "mic")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(engine.talking ? Theme.accent : Theme.text4)
                .help(engine.talking ? "Talking" : "Not talking (⌃⌥ Space)")
        }
    }

    private func dot(_ live: Bool) -> some View {
        Circle().fill(live ? Theme.ok : Theme.streamOff).frame(width: 6, height: 6)
    }

    private var dotsTooltip: String {
        func dir(_ name: String, _ s: SessionState, _ key: String) -> String {
            let lat = engine.latencyMs[key].map { String(format: ", %.1f s delay", $0 / 1000) } ?? ""
            return "\(name) \(s == .connected ? "live" : s.rawValue)\(lat)"
        }
        let cost = String(format: "$%.2f · ≈¥%d%@", engine.usd, Int((engine.usd * EngineProcess.jpyPerUSD).rounded()),
                          engine.costIsEstimate ? " est." : "")
        return [dir("IN", engine.inState, "in"), dir("OUT", engine.outState, "out"), cost].joined(separator: "\n")
    }
}

/// The bar's background: drags the window, and a double-click expands.
struct BarDragArea: NSViewRepresentable {
    var onDoubleClick: () -> Void

    func makeNSView(context: Context) -> NSView {
        let v = DragView()
        v.onDoubleClick = onDoubleClick
        return v
    }
    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? DragView)?.onDoubleClick = onDoubleClick
    }

    final class DragView: NSView {
        var onDoubleClick: () -> Void = {}
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 { onDoubleClick() } else { window?.performDrag(with: event) }
        }
        override var mouseDownCanMoveWindow: Bool { true }
    }
}

/// A short-lived borderless window that morphs between the panel and the bar: it shows a
/// snapshot of the panel cropped from the top (so the panel collapses into its header strip)
/// fading out over a solid bar background, while the window frame animates.
@MainActor
enum PanelBarTransition {
    static let duration: CFTimeInterval = 0.35
    static let timing = CAMediaTimingFunction(controlPoints: 0.6, 0, 0.3, 1)

    static func snapshot(_ view: NSView) -> CGImage? {
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return nil }
        view.cacheDisplay(in: view.bounds, to: rep)
        return rep.cgImage
    }

    /// Animates from `from` to `to`; `collapsing` decides which way the snapshot fades.
    ///
    /// Smoothness: the transition window never resizes. It covers both rectangles (plus room
    /// for the shadow) and stays still; only Core Animation layers move inside it, so every
    /// frame is composited on the GPU with no window redraws or per-step shadow recomputation.
    /// The snapshot is pinned to the top-left by animating the container's bounds origin, so
    /// the panel collapses into its header strip without the image sliding.
    /// `completion` runs at the end while this window is still on screen; call `finish` to
    /// remove it once whatever replaces it is visible (no gap, no blink).
    static func run(snapshot: CGImage?, from: NSRect, to: NSRect, collapsing: Bool,
                    reduceMotion: Bool, completion: @escaping (_ finish: @escaping () -> Void) -> Void) {
        let pad: CGFloat = 48
        let canvas = from.union(to).insetBy(dx: -pad, dy: -pad)
        let w = NSWindow(contentRect: canvas, styleMask: [.borderless], backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = false                      // the shadow is a layer that moves with the shape
        w.ignoresMouseEvents = true
        w.level = .popUpMenu
        w.isReleasedWhenClosed = false
        w.animationBehavior = .none
        WindowPrivacy.apply(w)

        let host = NSView(frame: NSRect(origin: .zero, size: canvas.size))
        host.wantsLayer = true
        host.layer?.backgroundColor = .clear
        w.contentView = host

        func local(_ r: NSRect) -> NSRect { r.offsetBy(dx: -canvas.minX, dy: -canvas.minY) }
        let a = local(from), b = local(to)
        let imgSize = collapsing ? from.size : to.size
        // Container geometry for a window-space rect: anchored top-left, bounds origin chosen so
        // sublayer y-range [imgH - h, imgH] (the top of the snapshot) is what shows.
        func bounds(_ r: NSRect) -> CGRect { CGRect(x: 0, y: imgSize.height - r.height, width: r.width, height: r.height) }
        func position(_ r: NSRect) -> CGPoint { CGPoint(x: r.minX, y: r.maxY) }
        let r0: CGFloat = collapsing ? 18 : 14, r1: CGFloat = collapsing ? 14 : 18

        let shadow = CALayer()
        shadow.anchorPoint = CGPoint(x: 0, y: 1)
        shadow.backgroundColor = Theme.ns(0x0E0E10).cgColor
        shadow.shadowColor = NSColor.black.cgColor
        shadow.shadowOpacity = 0.45
        shadow.shadowRadius = 18
        shadow.shadowOffset = CGSize(width: 0, height: -8)

        let box = CALayer()
        box.anchorPoint = CGPoint(x: 0, y: 1)
        box.masksToBounds = true
        box.backgroundColor = Theme.ns(0x0E0E10).cgColor
        box.borderColor = Theme.ns(0x26262A).cgColor
        box.borderWidth = 1

        let image = CALayer()
        image.contents = snapshot
        image.contentsGravity = .resize
        image.contentsScale = w.backingScaleFactor
        image.frame = CGRect(origin: .zero, size: imgSize)
        image.opacity = collapsing ? 1 : 0
        box.addSublayer(image)

        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for l in [shadow, box] {
            l.bounds = bounds(a); l.position = position(a); l.cornerRadius = r0
            host.layer?.addSublayer(l)
        }
        host.layer?.insertSublayer(shadow, below: box)
        CATransaction.commit()
        w.orderFrontRegardless()
        w.displayIfNeeded()

        let dur = reduceMotion ? 0.15 : duration
        let end = reduceMotion ? a : b
        func anim(_ key: String, _ from: Any, _ to: Any) -> CABasicAnimation {
            let x = CABasicAnimation(keyPath: key)
            x.fromValue = from; x.toValue = to; x.duration = dur; x.timingFunction = timing
            return x
        }
        CATransaction.begin()
        CATransaction.setCompletionBlock {
            MainActor.assumeIsolated {
                completion { w.orderOut(nil) }
            }
        }
        for l in [shadow, box] {
            l.add(anim("bounds", NSValue(rect: bounds(a)), NSValue(rect: bounds(end))), forKey: "bounds")
            l.add(anim("position", NSValue(point: position(a)), NSValue(point: position(end))), forKey: "position")
            l.add(anim("cornerRadius", r0, r1), forKey: "radius")
            l.bounds = bounds(end); l.position = position(end); l.cornerRadius = r1
        }
        image.add(anim("opacity", collapsing ? 1 : 0, collapsing ? 0 : 1), forKey: "fade")
        image.opacity = collapsing ? 0 : 1
        CATransaction.commit()
    }
}
