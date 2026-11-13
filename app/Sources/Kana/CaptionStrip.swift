import AppKit
import Combine
import SwiftUI

/// Hover state for the strip; the drag handle only shows while the pointer is over it.
@MainActor
final class CaptionHover: ObservableObject {
    @Published var inside = false
}

/// A floating, click-through caption strip for inbound translations. Borderless,
/// non-activating, above other windows on every Space, hidden from screen share by default.
/// Independent of the panel, so it works while the panel is closed.
@MainActor
final class CaptionController: NSObject, NSWindowDelegate {
    static let size = NSSize(width: 592, height: 110)   // 28 handle + 4 gap + 560 box
    /// The handle sits at the bottom-left of the window, in window coordinates.
    static let handleRect = NSRect(x: 0, y: 0, width: 28, height: 56)

    private let engine: EngineProcess
    private let prefs: Prefs
    private let hover = CaptionHover()
    private var panel: NSPanel?
    private var pointerTimer: Timer?
    private var bag = Set<AnyCancellable>()

    init(engine: EngineProcess, prefs: Prefs) {
        self.engine = engine
        self.prefs = prefs
        super.init()
        // The minimized bar is the captions; the strip comes back on expand if it was on.
        prefs.$captionsOn.combineLatest(prefs.$minimized)
            .receive(on: RunLoop.main)
            .sink { [weak self] on, minimized in self?.setVisible(on && !minimized) }
            .store(in: &bag)
    }

    private func setVisible(_ on: Bool) {
        if on {
            if panel == nil { build() }
            if let p = panel { WindowPrivacy.apply(p); p.orderFrontRegardless() }
            startPointerWatch()
        } else {
            panel?.orderOut(nil)
            pointerTimer?.invalidate()
            pointerTimer = nil
        }
    }

    private func build() {
        let p = NSPanel(contentRect: NSRect(origin: .zero, size: Self.size),
                        styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        p.level = .floating
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false
        p.ignoresMouseEvents = true
        p.hidesOnDeactivate = false
        p.isReleasedWhenClosed = false
        p.becomesKeyOnlyIfNeeded = true
        p.title = "\(Theme.name) captions"   // borderless, never shown; l10n:skip
        p.delegate = self
        let view = CaptionView()
            .environmentObject(engine)
            .environmentObject(hover)
        p.contentView = NSHostingView(rootView: view)
        p.setFrameOrigin(savedOrigin() ?? defaultOrigin())
        WindowPrivacy.apply(p)
        panel = p
    }

    /// Bottom centre of the main screen, above the Dock.
    private func defaultOrigin() -> NSPoint {
        let vf = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
        return NSPoint(x: vf.midX - Self.size.width / 2, y: vf.minY + 24)
    }

    private func savedOrigin() -> NSPoint? {
        guard let s = UserDefaults.standard.string(forKey: "captionOrigin") else { return nil }
        let p = NSPointFromString(s)
        // Ignore a saved spot that is no longer on any screen (display unplugged).
        let rect = NSRect(origin: p, size: Self.size)
        return NSScreen.screens.contains { $0.frame.intersects(rect) } ? p : nil
    }

    func windowDidMove(_ notification: Notification) {
        guard let p = panel else { return }
        UserDefaults.standard.set(NSStringFromPoint(p.frame.origin), forKey: "captionOrigin")
    }

    /// Click-through except over the drag handle: polls the pointer (a click-through window gets
    /// no mouse events, so it cannot track hover itself).
    private func startPointerWatch() {
        guard pointerTimer == nil else { return }
        pointerTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.checkPointer() }
        }
    }

    private func checkPointer() {
        guard let p = panel, p.isVisible else { return }
        let mouse = NSEvent.mouseLocation
        let inside = p.frame.contains(mouse)
        if hover.inside != inside { hover.inside = inside }
        let handle = Self.handleRect.offsetBy(dx: p.frame.minX, dy: p.frame.minY)
        let overHandle = handle.contains(mouse)
        // Keep events while dragging (button held) so the drag is not cut off.
        let dragging = NSEvent.pressedMouseButtons & 1 == 1 && !p.ignoresMouseEvents
        let ignore = !(overHandle || dragging)
        if p.ignoresMouseEvents != ignore { p.ignoresMouseEvents = ignore }
    }
}

/// The strip's content: last two inbound translations, fading 8 s after their last update.
struct CaptionView: View {
    @EnvironmentObject private var engine: EngineProcess
    @EnvironmentObject private var hover: CaptionHover

    static let hold: TimeInterval = 8
    static let fade: TimeInterval = 0.6

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { ctx in
            let lines = visibleLines(now: ctx.date)
            HStack(alignment: .bottom, spacing: 4) {
                DragHandle()
                    .frame(width: 24, height: 48)
                    .opacity(hover.inside ? 1 : 0)
                if !lines.isEmpty || hover.inside {
                    box(lines)
                } else {
                    Spacer()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            .animation(.easeOut(duration: 0.2), value: lines.map(\.0.id))
        }
    }

    /// Small and quiet: max 560 pt wide, 17 pt text, the newest line plus the previous one at
    /// 60 %, and the kana tag only while the pointer is over the strip.
    private func box(_ lines: [(TranscriptRow, Double)]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if hover.inside {
                HStack(spacing: 6) {
                    KanaMark(state: .idle, size: 10)
                    Text(Theme.name).font(Theme.brand(10)).foregroundStyle(Theme.text4)
                }
            }
            if lines.isEmpty {
                Text(L10n.t("Captions appear here. Drag the handle to move."))
                    .font(Theme.ui(13))
                    .foregroundStyle(Theme.text4)
            }
            ForEach(Array(lines.enumerated()), id: \.element.0.id) { i, item in
                Text(item.0.dst)
                    .font(Theme.text(item.0.dst, size: 17, weight: 500))
                    .foregroundStyle(Theme.text)
                    .opacity(item.1 * (i == lines.count - 1 ? 1 : 0.6))
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(maxWidth: 560, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Theme.bg.opacity(0.72)))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Theme.line.opacity(0.7)))
    }

    /// Last two inbound rows with a translation, each with its fade opacity.
    private func visibleLines(now: Date) -> [(TranscriptRow, Double)] {
        let inbound = engine.rows.filter { $0.dir == .inbound && !$0.dst.isEmpty }.suffix(2)
        return inbound.compactMap { row in
            let age = now.timeIntervalSince(row.updatedAt)
            let opacity = age <= Self.hold ? 1 : max(0, 1 - (age - Self.hold) / Self.fade)
            return opacity > 0 ? (row, opacity) : nil
        }
    }
}

/// Grip shown on hover; dragging it moves the strip.
struct DragHandle: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { HandleView() }
    func updateNSView(_ nsView: NSView, context: Context) {}

    final class HandleView: NSView {
        override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
        override func draw(_ dirtyRect: NSRect) {
            let pill = NSBezierPath(roundedRect: bounds.insetBy(dx: 2, dy: 2), xRadius: 8, yRadius: 8)
            Theme.ns(0x151518, 0.95).setFill()
            pill.fill()
            NSColor(white: 1, alpha: 0.7).setFill()
            for i in 0..<3 {
                let y = bounds.midY - 8 + CGFloat(i) * 8
                NSBezierPath(ovalIn: NSRect(x: bounds.midX - 2.5, y: y - 2, width: 4, height: 4)).fill()
                NSBezierPath(ovalIn: NSRect(x: bounds.midX + 1.5, y: y - 2, width: 4, height: 4)).fill()
            }
        }
        override func resetCursorRects() { addCursorRect(bounds, cursor: .openHand) }
    }
}
