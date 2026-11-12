import AppKit
import ApplicationServices

/// Global ⌃⌥Space. The global monitor only receives key events once the app is trusted for
/// Accessibility; the local monitor covers the case where our own panel has focus.
@MainActor
final class Hotkey: ObservableObject {
    static let hint = "⌃⌥Space"
    nonisolated private static let spaceKeyCode: UInt16 = 49

    @Published private(set) var trusted = AXIsProcessTrusted()

    private var globalMonitor: Any?
    private var localMonitor: Any?
    private var pollTimer: Timer?
    private let onFire: @MainActor () -> Void

    init(onFire: @escaping @MainActor () -> Void) {
        self.onFire = onFire
    }

    func install() {
        installMonitors()
        if !trusted { startPolling() }
    }

    /// Adds the app to the Accessibility list (prompting once) and opens the settings pane.
    func requestAccess() {
        let key = "AXTrustedCheckOptionPrompt" as CFString
        _ = AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
        startPolling()
    }

    func recheck() {
        let now = AXIsProcessTrusted()
        if now != trusted {
            trusted = now
            installMonitors()  // re-add the global monitor so it starts receiving events
        }
    }

    private func startPolling() {
        guard pollTimer == nil else { return }
        pollTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.recheck()
                if self.trusted { self.pollTimer?.invalidate(); self.pollTimer = nil }
            }
        }
    }

    private func installMonitors() {
        if let g = globalMonitor { NSEvent.removeMonitor(g) }
        if let l = localMonitor { NSEvent.removeMonitor(l) }
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard Self.matches(event) else { return }
            MainActor.assumeIsolated { self?.onFire() }
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard Self.matches(event) else { return event }
            MainActor.assumeIsolated { self?.onFire() }
            return nil
        }
    }

    nonisolated private static func matches(_ event: NSEvent) -> Bool {
        guard event.keyCode == spaceKeyCode, !event.isARepeat else { return false }
        let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            .subtracting([.capsLock, .numericPad, .function])
        return mods == [.control, .option]
    }
}
