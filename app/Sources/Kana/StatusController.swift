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
    private var bar: MiniBarController!
    private var transitioning = false
    private var introPlayed = false   // the opening intro plays once per launch
    private let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

    init(engine: EngineProcess, hotkey: Hotkey, prefs: Prefs, actions: AppActions) {
        self.engine = engine
        self.prefs = prefs
        self.actions = actions

        panel = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: 440, height: 720),
                         styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
                         backing: .buffered, defer: true)
        super.init()

        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.delegate = self
        panel.title = Theme.name

        let root = PanelView()
            .environmentObject(engine)
            .environmentObject(hotkey)
            .environmentObject(prefs)
            .environmentObject(actions)
        let host = NSHostingController(rootView: root)
        // The window frame is set here (it changes height during the opening intro).
        host.sizingOptions = []
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
        actions.minimize = { [weak self] in self?.minimize() }
        actions.expand = { [weak self] in self?.expand() }
        actions.closeBar = { [weak self] in self?.bar.hide() }
        bar = MiniBarController(engine: engine, prefs: prefs, actions: actions)
    }

    /// At launch: the bar if the user left kana minimized, otherwise the panel with its intro.
    func launch(attempt: Int = 0) {
        // The status item gets its place in the menu bar a moment after launch; wait for it so
        // the panel opens under the icon instead of at a stale origin.
        let placed = (item.button?.window?.frame.minY ?? 0) > 0
        if !placed && attempt < 20 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in self?.launch(attempt: attempt + 1) }
            return
        }
        if prefs.minimized {
            bar.show(at: bar.savedFrame ?? defaultBarFrame(), fadeIn: true)
        } else {
            show()
        }
    }

    private func updateIcon() {
        item.button?.image = MenuIcon.image(talking: engine.talking)
    }

    // MARK: Show / hide

    @objc private func clicked(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp {
            showContextMenu()
        } else if transitioning {
            return
        } else if prefs.minimized {
            // Minimized: bring the bar back, or expand it if it is already showing.
            if bar.window.isVisible { expand() } else { bar.show(at: bar.savedFrame ?? defaultBarFrame(), fadeIn: true) }
        } else if panel.isVisible {
            // Only the panel's × closes it; the icon just brings it forward.
            panel.orderFrontRegardless()
        } else {
            show()
        }
    }

    /// Brings kana to the front without toggling it closed (used when the app is launched again).
    func reopen() {
        guard !transitioning else { return }
        if prefs.minimized {
            if bar.window.isVisible { expand() } else { bar.show(at: bar.savedFrame ?? defaultBarFrame(), fadeIn: true) }
        } else if !panel.isVisible {
            show()
        } else {
            NSApp.activate(ignoringOtherApps: true)
            panel.makeKeyAndOrderFront(nil)
        }
    }

    /// Opens the panel. From idle it plays the opening intro: the window opens compact
    /// (440 × 220) and grows to full height, anchored at the top, once the mark has traced
    /// itself. During a live session, or under reduced motion, it opens at full size with a fade.
    func show(animated: Bool = true) {
        WindowPrivacy.apply(panel)
        let full = PanelView.size
        setPanelHeight(full.height)
        position()
        NSApp.activate(ignoringOtherApps: true)
        if animated && !engine.running && !reduceMotion && !introPlayed {
            introPlayed = true
            let start = Date()
            actions.introStart = start
            setPanelHeight(PanelView.compactHeight)
            panel.alphaValue = 1
            DispatchQueue.main.asyncAfter(deadline: .now() + PanelView.growStart) { [weak self] in
                guard let self, self.actions.introStart == start, self.panel.isVisible else { return }
                NSAnimationContext.runAnimationGroup { ctx in
                    ctx.duration = PanelView.growDuration
                    ctx.timingFunction = PanelBarTransition.timing
                    self.panel.animator().setFrame(self.frame(height: full.height), display: true)
                }
            }
        } else if animated {
            panel.alphaValue = 0
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.15
                panel.animator().alphaValue = 1
            }
        } else {
            panel.alphaValue = 1
        }
        panel.makeKeyAndOrderFront(nil)
        // No text field gets focus on open, so typing meant for another app (or a stray
        // keystroke) never lands in the API key field.
        DispatchQueue.main.async { [weak self] in self?.panel.makeFirstResponder(nil) }
        item.button?.highlight(true)
        NotificationCenter.default.post(name: .kanaPanelDidOpen, object: nil)
    }

    func hide() {
        guard !transitioning else { return }
        panel.orderOut(nil)
        item.button?.highlight(false)
        if let m = outsideClickMonitor { NSEvent.removeMonitor(m); outsideClickMonitor = nil }
    }

    /// Top-centre under the status item, clamped to the screen.
    private func position() {
        var anchor = item.button?.window?.frame ?? .zero
        let screen = item.button?.window?.screen ?? NSScreen.main
        if anchor.minY <= 0, let vf = (screen ?? NSScreen.screens.first)?.visibleFrame {
            // Not placed yet: top right of the screen, under the menu bar.
            anchor = NSRect(x: vf.maxX - 260, y: vf.maxY, width: 24, height: 24)
        }
        let size = panel.frame.size
        var x = anchor.midX - size.width / 2
        if let vf = screen?.visibleFrame {
            x = min(max(x, vf.minX + 8), vf.maxX - size.width - 8)
        }
        panel.setFrameTopLeftPoint(NSPoint(x: x, y: anchor.minY - 6))
    }

    /// The panel's frame at a given height, keeping its top edge where it is.
    private func frame(height: CGFloat) -> NSRect {
        let f = panel.frame
        return NSRect(x: f.minX, y: f.maxY - height, width: PanelView.size.width, height: height)
    }

    private func setPanelHeight(_ height: CGFloat) {
        panel.setFrame(frame(height: height), display: false)
    }


    // MARK: Minimized bar

    /// Default bar spot: the panel's header area (top-left of the panel).
    private func defaultBarFrame() -> NSRect {
        if panel.frame.width > 0 && panel.isVisible {
            return NSRect(x: panel.frame.minX, y: panel.frame.maxY - MiniBarController.size.height,
                          width: MiniBarController.size.width, height: MiniBarController.size.height)
        }
        let vf = (item.button?.window?.screen ?? NSScreen.main ?? NSScreen.screens[0]).visibleFrame
        return NSRect(x: vf.maxX - MiniBarController.size.width - 24, y: vf.maxY - MiniBarController.size.height - 12,
                      width: MiniBarController.size.width, height: MiniBarController.size.height)
    }

    /// Collapses the panel into the bar: the panel shrinks from the top into the bar's frame
    /// while the content below the header fades (~350 ms).
    func minimize() {
        guard !transitioning else { return }
        let target = bar.savedFrame ?? defaultBarFrame()
        prefs.minimized = true
        guard panel.isVisible, let view = panel.contentView else {
            bar.show(at: target, fadeIn: true)
            return
        }
        // Minimizing during the opening intro: stop it, settle the panel at full height, and
        // minimize on the next beat, so the snapshot is the finished panel (not a half-grown
        // frame with the mark mid-flight).
        if let s = actions.introStart, Date().timeIntervalSince(s) < PanelView.introLength + 0.1 {
            actions.introStart = nil
            panel.setFrame(frame(height: PanelView.size.height), display: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.06) { [weak self] in self?.minimize() }
            return
        }
        transitioning = true
        let snap = PanelBarTransition.snapshot(view)
        let from = panel.frame
        item.button?.highlight(false)
        if let m = outsideClickMonitor { NSEvent.removeMonitor(m); outsideClickMonitor = nil }
        // The transition window is on screen before the panel goes, and stays until the bar has
        // faded in on top of it: there is never a frame with neither.
        PanelBarTransition.run(snapshot: snap, from: from, to: target, collapsing: true, reduceMotion: reduceMotion) { [weak self] finish in
            guard let self else { finish(); return }
            self.bar.show(at: target, fadeIn: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.14) {
                finish()
                self.transitioning = false
            }
        }
        DispatchQueue.main.async { [weak self] in self?.panel.orderOut(nil) }
    }

    /// Reverse: the bar grows back into the panel.
    func expand() {
        guard !transitioning else { return }
        prefs.minimized = false
        let from = bar.window.isVisible ? bar.window.frame : defaultBarFrame()
        setPanelHeight(PanelView.size.height)
        position()
        let to = panel.frame
        transitioning = true
        let snap = panel.contentView.flatMap(PanelBarTransition.snapshot)
        PanelBarTransition.run(snapshot: snap, from: from, to: to, collapsing: false, reduceMotion: reduceMotion) { [weak self] finish in
            self?.transitioning = false
            self?.show(animated: false)
            DispatchQueue.main.async { finish() }   // panel is up; now drop the transition layer
        }
        DispatchQueue.main.async { [weak self] in self?.bar.hide() }
    }

    // MARK: Right-click menu (works while the panel is closed)

    private func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(actions.menuItem(L10n.t("Captions"), state: prefs.captionsOn) { [weak self] in
            self?.prefs.captionsOn.toggle()
        })
        let keys = NSMenu()
        for key in TalkKey.allCases {
            keys.addItem(actions.menuItem(key.title, state: prefs.talkKey == key) { [weak self] in
                self?.prefs.talkKey = key
            })
        }
        let keyItem = NSMenuItem(title: L10n.t("Talk key"), action: nil, keyEquivalent: "")
        keyItem.submenu = keys
        menu.addItem(keyItem)
        let langs = NSMenu()
        for (choice, title) in [(L10n.Choice.system, L10n.t("System")), (.en, "English"), (.ja, "日本語")] {
            langs.addItem(actions.menuItem(title, state: prefs.language == choice) { [weak self] in
                self?.prefs.language = choice
            })
        }
        let langItem = NSMenuItem(title: L10n.t("Language"), action: nil, keyEquivalent: "")
        langItem.submenu = langs
        menu.addItem(langItem)
        menu.addItem(actions.menuItem(L10n.t("Keep Meet Audio On When Not Translating"), state: prefs.passthroughWhenIdle) { [weak self] in
            guard let self else { return }
            self.prefs.passthroughWhenIdle.toggle()
            self.engine.passthroughPrefChanged()
        })
        menu.addItem(.separator())
        let last = actions.menuItem(L10n.t("Open Last Transcript")) { [weak self] in self?.actions.openLastTranscript() }
        last.isEnabled = actions.lastTranscriptURL != nil
        menu.addItem(last)
        menu.addItem(actions.menuItem(L10n.t("Transcripts Folder")) { [weak self] in self?.actions.openTranscriptsFolder() })
        menu.addItem(actions.menuItem(L10n.t("Setup…")) { [weak self] in self?.actions.openSetup() })
        menu.addItem(.separator())
        menu.addItem(actions.menuItem(L10n.t("Quit kana")) { [weak self] in self?.actions.quit() })
        item.menu = menu
        item.button?.performClick(nil)   // shows the menu at the item
        item.menu = nil                  // left click goes back to the panel
    }
}

extension Notification.Name {
    static let kanaPanelDidOpen = Notification.Name("kanaPanelDidOpen")
}
