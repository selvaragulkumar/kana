import AppKit
import QuartzCore
import SwiftUI

/// Pointer-over state for the bar; the expand and close buttons show only while it is inside.
@MainActor
final class BarHover: ObservableObject {
    @Published var inside = false
}

/// The minimized panel, which is also the caption surface (docs/superpowers/specs/
/// 2026-11-16-minibar-captions.md): a 640 × 108 floating bar with the mark (Start / Stop), the
/// latest inbound translation large with the previous one above it, and the IN/OUT dots and a
/// talk button on the right. Always on top, on all Spaces, hidden from screen share like the
/// panel, draggable by its background, position persisted.
@MainActor
final class MiniBarController: NSObject, NSWindowDelegate {
    static let size = NSSize(width: 640, height: 108)
    let window: NSPanel
    private let hover = BarHover()

    init(engine: EngineProcess, prefs: Prefs, actions: AppActions) {
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
        window.title = "\(Theme.name) bar"   // borderless, never shown; l10n:skip
        window.delegate = self
        let view = MiniBarView(onExpand: { actions.expand() }, onClose: { actions.closeBar() })
            .environmentObject(engine)
            .environmentObject(hover)
            .environmentObject(prefs)
        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: Self.size)
        window.contentView = host
        WindowPrivacy.apply(window)
    }

    /// The saved spot, clamped onto a screen; nil if none was saved (the caller picks one).
    var savedFrame: NSRect? {
        guard let s = UserDefaults.standard.string(forKey: "miniOrigin") else { return nil }
        return Self.clamped(NSRect(origin: NSPointFromString(s), size: Self.size))
    }

    /// Moves a bar frame fully onto the visible area of the screen it overlaps most (the main
    /// screen if none), so a spot saved for the old, smaller bar or on an unplugged display
    /// still shows the whole bar.
    static func clamped(_ r: NSRect) -> NSRect {
        let screens = NSScreen.screens
        guard let fallback = NSScreen.main ?? screens.first else { return r }
        func overlap(_ s: NSScreen) -> CGFloat {
            let i = s.visibleFrame.intersection(r)
            return i.isNull ? 0 : i.width * i.height
        }
        let best = screens.max { overlap($0) < overlap($1) }
        let vf = (best.flatMap { overlap($0) > 0 ? $0 : nil } ?? fallback).visibleFrame
        let x = min(max(r.minX, vf.minX), vf.maxX - r.width)
        let y = min(max(r.minY, vf.minY), vf.maxY - r.height)
        return NSRect(x: x, y: y, width: r.width, height: r.height)
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

/// Bar content. The mark is Start / Stop, the mic toggles talk; a double-click on the bar or the
/// hover button expands.
struct MiniBarView: View {
    @EnvironmentObject private var engine: EngineProcess
    @EnvironmentObject private var hover: BarHover
    @EnvironmentObject private var prefs: Prefs
    var onExpand: () -> Void
    var onClose: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Button {
                if engine.running { engine.stop() } else { engine.startWithSavedPrefs() }
            } label: {
                KanaMark(state: markState, size: 32)
                    .modifier(Breathe(active: breathing))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(engine.running ? L10n.t("Stop") : L10n.t("Start"))
            .onHover { inside in
                if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
            }

            lines
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: hasCaption ? .bottomLeading : .leading)
                .allowsHitTesting(false)

            controls
        }
        .padding(.leading, 16)
        .padding(.trailing, 10)
        .padding(.vertical, 12)
        .frame(width: MiniBarController.size.width, height: MiniBarController.size.height)
        .background(BarDragArea(onDoubleClick: onExpand))
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.bg))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.line).allowsHitTesting(false))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .environment(\.colorScheme, .dark)
        .onHover { hover.inside = $0 }
    }

    /// The captions: latest inbound translation (20 pt, up to two lines, head-truncated so the
    /// newest words stay visible) with the previous one above it (14 pt, dimmed, one line);
    /// a new line slides up into place.
    private var lines: some View {
        let inbound = engine.rows.filter { $0.dir == .inbound && !$0.dst.isEmpty }
        let latest = inbound.last
        let previous = inbound.dropLast().last
        return VStack(alignment: .leading, spacing: 3) {
            if let previous {
                Text(previous.dst)
                    .font(Theme.text(previous.dst, size: 14))
                    .foregroundStyle(Theme.text4)
                    .lineLimit(1)
                    .truncationMode(.head)
                    .id("p-\(previous.id)")
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
            if let latest {
                // Two lines at most, showing the end: a hidden two-line copy sets the height, the
                // full text sits on its bottom edge and the oldest lines are clipped off the top,
                // so a long turn scrolls up like a caption instead of truncating mid-sentence.
                let font = Theme.text(latest.dst, size: 20, weight: 500)
                Text(latest.dst)
                    .font(font)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)   // never squeezed to one line
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .hidden()
                    .overlay(alignment: .bottomLeading) {
                        Text(latest.dst)
                            .font(font)
                            .foregroundStyle(Theme.textStrong)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .clipped()
                    .id("l-\(latest.id)")
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            } else {
                Text(engine.running ? L10n.t("Listening…")
                     : engine.passingThrough ? L10n.t("Not translating · mute in Meet") : L10n.t("Idle. Click the mark to start."))
                    .font(Theme.ui(14))
                    .foregroundStyle(Theme.text4)
                    .lineLimit(1)
            }
        }
        .clipped()
        .animation(.easeOut(duration: 0.25), value: latest?.id)
    }

    /// Talking shows the talking mark; a connected session shows the still mark breathing
    /// (one motion only, not the listening brackets as well); connecting, error and idle (also
    /// pass-through) are the engine's mark state.
    private var markState: MarkState {
        if engine.running && engine.talking { return .talking }
        if engine.markState == .listening { return .idle }
        return engine.markState
    }

    private var breathing: Bool { engine.running && !engine.talking && engine.markState == .listening }

    private var hasCaption: Bool { engine.rows.contains { $0.dir == .inbound && !$0.dst.isEmpty } }

    /// Right column, vertically centred: the IN/OUT dots, swapped for expand and close while the
    /// pointer is over the bar (same width either way, so the captions never reflow), and the
    /// mic button, always there.
    private var controls: some View {
        HStack(spacing: 6) {
            ZStack(alignment: .trailing) {
                HStack(spacing: 4) {
                    dot(engine.inState == .connected)
                    dot(engine.outState == .connected)
                }
                .padding(.trailing, 4)
                .help(dotsTooltip)
                .opacity(hover.inside ? 0 : 1)
                HStack(spacing: 2) {
                    Button(action: onExpand) {
                        Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 12, weight: .semibold))
                    }
                    .buttonStyle(IconButtonStyle())
                    .help(L10n.t("Expand"))
                    Button(action: onClose) {
                        Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                    }
                    .buttonStyle(IconButtonStyle())
                    .help(L10n.t("Close"))
                }
                .opacity(hover.inside ? 1 : 0)
                .allowsHitTesting(hover.inside)
            }
            micButton
        }
        .fixedSize()
    }

    /// Toggles talk exactly like the panel's talk bar (and a tap of the talk key); only while live.
    private var micButton: some View {
        let on = engine.talking
        let enabled = engine.running && engine.ready
        return Button {
            engine.toggleTalk()
        } label: {
            Image(systemName: on ? "mic.fill" : "mic")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(on ? Theme.accent : Theme.text4)
                .frame(width: 28, height: 28)
                .background(Circle().fill(on ? Theme.accentBg : (enabled ? Theme.surface : .clear)))
                .overlay(Circle().strokeBorder(on ? Theme.accent : (enabled ? Theme.line : .clear)))
                .contentShape(Circle())
                .opacity(enabled ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .help(enabled ? talkHelp : L10n.t("Start a session first"))
        .onHover { inside in
            guard enabled else { return }
            if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
        }
    }

    private var talkHelp: String {
        prefs.talkKey.isModifier
            ? L10n.f("Toggle talking, or hold %@ to talk and tap it to toggle", prefs.talkKey.hint)
            : L10n.f("Toggle talking (%@)", prefs.talkKey.hint)
    }

    private func dot(_ live: Bool) -> some View {
        Circle().fill(live ? Theme.ok : Theme.streamOff).frame(width: 6, height: 6)
    }

    private var dotsTooltip: String {
        func dir(_ name: String, _ s: SessionState, _ key: String) -> String {
            let lat = engine.latencyMs[key].map { L10n.f(", %.1f s delay", $0 / 1000) } ?? ""
            return "\(name) \(s == .connected ? L10n.t("live") : s.spoken)\(lat)"
        }
        let cost = String(format: "$%.2f · ≈¥%d%@", engine.usd, Int((engine.usd * EngineProcess.jpyPerUSD).rounded()),
                          engine.costIsEstimate ? " " + L10n.t("est.") : "")
        return [dir("IN", engine.inState, "in"), dir("OUT", engine.outState, "out"), cost].joined(separator: "\n")
    }
}

/// The mini bar mark's live pulse: scale 1.0 → 1.06 and opacity 0.85 → 1, 0.9 s each way
/// (1.8 s period). Under Reduce Motion only the opacity changes, more gently.
struct Breathe: ViewModifier {
    let active: Bool
    private let reduce = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

    func body(content: Content) -> some View {
        if active {
            content.phaseAnimator([false, true]) { view, up in
                view
                    .scaleEffect(up && !reduce ? 1.06 : 1)
                    .opacity(up ? 1 : (reduce ? 0.9 : 0.85))
            } animation: { _ in .easeInOut(duration: 0.9) }
        } else {
            content
        }
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
