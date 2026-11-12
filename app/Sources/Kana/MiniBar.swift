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
    static func run(snapshot: CGImage?, from: NSRect, to: NSRect, collapsing: Bool,
                    reduceMotion: Bool, completion: @escaping () -> Void) {
        let w = NSWindow(contentRect: from, styleMask: [.borderless], backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = true
        w.level = .popUpMenu
        w.isReleasedWhenClosed = false
        WindowPrivacy.apply(w)

        let host = NSView(frame: NSRect(origin: .zero, size: from.size))
        host.wantsLayer = true
        let root = host.layer!
        root.masksToBounds = true
        root.cornerRadius = collapsing ? 18 : 14
        root.backgroundColor = Theme.ns(0x0E0E10).cgColor
        root.borderColor = Theme.ns(0x26262A).cgColor
        root.borderWidth = 1

        let image = CALayer()
        image.contents = snapshot
        image.contentsGravity = .topLeft
        image.contentsScale = w.backingScaleFactor
        image.isGeometryFlipped = false
        image.frame = root.bounds
        image.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        image.opacity = collapsing ? 1 : 0
        root.addSublayer(image)
        w.contentView = host
        w.orderFrontRegardless()

        let dur = reduceMotion ? 0.15 : duration
        CATransaction.begin()
        CATransaction.setAnimationDuration(dur)
        CATransaction.setAnimationTimingFunction(timing)
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = collapsing ? 1 : 0
        fade.toValue = collapsing ? 0 : 1
        fade.duration = dur
        fade.timingFunction = timing
        image.add(fade, forKey: "fade")
        image.opacity = collapsing ? 0 : 1
        let radius = CABasicAnimation(keyPath: "cornerRadius")
        radius.fromValue = collapsing ? 18 : 14
        radius.toValue = collapsing ? 14 : 18
        radius.duration = dur
        root.add(radius, forKey: "radius")
        root.cornerRadius = collapsing ? 14 : 18
        CATransaction.commit()

        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = dur
            ctx.timingFunction = timing
            w.animator().setFrame(reduceMotion ? from : to, display: true)
        }, completionHandler: {
            MainActor.assumeIsolated {
                completion()
                w.orderOut(nil)
            }
        })
    }
}
