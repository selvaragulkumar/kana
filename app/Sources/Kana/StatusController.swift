import AppKit
import Combine
import SwiftUI

/// Borderless panels refuse key status by default; the panel needs it for text fields.
final class KeyPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

/// The menu-bar item and its panel. Built on NSStatusItem + NSPanel rather than SwiftUI's
/// MenuBarExtra, because MenuBarExtra's window cannot be switched back to `sharingType = .none`
/// once it was shareable (verified on macOS 26.4), and hiding from screen share must be reliable.
@MainActor
final class StatusController: NSObject, NSWindowDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let panel: KeyPanel
    private let engine: EngineProcess
    private let prefs: Prefs
    private let actions: AppActions
    private var outsideClickMonitor: Any?
    private var bag = Set<AnyCancellable>()

    init(engine: EngineProcess, hotkey: Hotkey, prefs: Prefs, actions: AppActions) {
        self.engine = engine
        self.prefs = prefs
        self.actions = actions

        panel = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: 440, height: 720),
                         styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
                         backing: .buffered, defer: true)
        super.init()

        panel.level = .popUpMenu
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        panel.delegate = self
        panel.title = Theme.name

        let root = PanelView()
            .environmentObject(engine)
            .environmentObject(hotkey)
            .environmentObject(prefs)
            .environmentObject(actions)
        let host = NSHostingController(rootView: root)
        host.sizingOptions = [.preferredContentSize]
        // The panel draws its own opaque, rounded background (design: no glass).
        host.view.wantsLayer = true
        host.view.layer?.backgroundColor = .clear
        panel.contentViewController = host
        WindowPrivacy.apply(panel)

        if let button = item.button {
            button.toolTip = Theme.name
            button.target = self
            button.action = #selector(clicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        updateIcon()
        engine.$talking.combineLatest(engine.$running)
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.updateIcon() }
            .store(in: &bag)
        actions.showPanel = { [weak self] in self?.show() }
        actions.hidePanel = { [weak self] in self?.hide() }
    }

    private func updateIcon() {
        item.button?.image = MenuIcon.image(talking: engine.talking)
    }

    // MARK: Show / hide

    @objc private func clicked(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp {
            showContextMenu()
        } else if panel.isVisible {
            hide()
        } else {
            show()
        }
    }

    func show() {
        WindowPrivacy.apply(panel)
        position()
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        // No text field gets focus on open, so typing meant for another app (or a stray
        // keystroke) never lands in the API key field.
        DispatchQueue.main.async { [weak self] in self?.panel.makeFirstResponder(nil) }
        item.button?.highlight(true)
        outsideClickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            MainActor.assumeIsolated { self?.hide() }
        }
        NotificationCenter.default.post(name: .kanaPanelDidOpen, object: nil)
    }

    func hide() {
        panel.orderOut(nil)
        item.button?.highlight(false)
        if let m = outsideClickMonitor { NSEvent.removeMonitor(m); outsideClickMonitor = nil }
    }

    /// Top-centre under the status item, clamped to the screen.
    private func position() {
        guard let buttonWindow = item.button?.window else { return }
        let anchor = buttonWindow.frame
        let screen = buttonWindow.screen ?? NSScreen.main
        let size = panel.frame.size
        var x = anchor.midX - size.width / 2
        if let vf = screen?.visibleFrame {
            x = min(max(x, vf.minX + 8), vf.maxX - size.width - 8)
        }
        panel.setFrameTopLeftPoint(NSPoint(x: x, y: anchor.minY - 6))
    }

    func windowDidResize(_ notification: Notification) {
        if panel.isVisible { position() }
    }

    func windowDidResignKey(_ notification: Notification) {
        // Closing while a menu from the panel is open would kill the menu; menus keep key.
        if NSApp.isActive == false { hide() }
    }

    // MARK: Right-click menu (works while the panel is closed)

    private func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(actions.menuItem("Captions", state: prefs.captionsOn) { [weak self] in
            self?.prefs.captionsOn.toggle()
        })
        menu.addItem(.separator())
        let last = actions.menuItem("Open Last Transcript") { [weak self] in self?.actions.openLastTranscript() }
        last.isEnabled = actions.lastTranscriptURL != nil
        menu.addItem(last)
        menu.addItem(actions.menuItem("Transcripts Folder") { [weak self] in self?.actions.openTranscriptsFolder() })
        menu.addItem(actions.menuItem("Setup…") { [weak self] in self?.actions.openSetup() })
        menu.addItem(.separator())
        menu.addItem(actions.menuItem("Quit kana") { NSApp.terminate(nil) })
        item.menu = menu
        item.button?.performClick(nil)   // shows the menu at the item
        item.menu = nil                  // left click goes back to the panel
    }
}

extension Notification.Name {
    static let kanaPanelDidOpen = Notification.Name("kanaPanelDidOpen")
}
