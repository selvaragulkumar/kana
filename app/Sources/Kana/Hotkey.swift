import AppKit
import ApplicationServices
import Combine

/// The talk key the user picked (••• › Talk key). The three modifier keys are watched on
/// `.flagsChanged` and support hold-to-talk and tap-to-toggle; ⌃⌥Space is the old toggle.
enum TalkKey: String, CaseIterable, Identifiable {
    case rightOption, rightCommand, fn, ctrlOptSpace

    var id: String { rawValue }

    /// Virtual key code of the key itself (kVK_RightOption, kVK_RightCommand, kVK_Function, kVK_Space).
    var keyCode: UInt16 {
        switch self {
        case .rightOption: return 61
        case .rightCommand: return 54
        case .fn: return 63
        case .ctrlOptSpace: return 49
        }
    }

    /// Hold to talk, tap to toggle. ⌃⌥Space only toggles.
    var isModifier: Bool { self != .ctrlOptSpace }

    /// Short form for the talk bar pill and tooltips.
    var hint: String {
        switch self {
        case .rightOption: return L10n.t("⌥ right")
        case .rightCommand: return L10n.t("⌘ right")
        case .fn: return "fn"
        case .ctrlOptSpace: return "⌃⌥Space"
        }
    }

    /// Menu title.
    var title: String {
        switch self {
        case .rightOption: return L10n.t("Right ⌥ (hold or tap)")
        case .rightCommand: return L10n.t("Right ⌘ (hold or tap)")
        case .fn: return L10n.t("Fn / 🌐 (hold or tap)")
        case .ctrlOptSpace: return L10n.t("⌃⌥Space (toggle)")
        }
    }

    /// Extra advice shown under the picker, if any.
    var note: String? {
        self == .fn ? L10n.t("Set Keyboard › “Press 🌐 key to” to “Do Nothing”, or Fn opens the emoji picker.") : nil
    }

    /// Whether the key is down in a `.flagsChanged` event's raw flags. Right ⌥ and right ⌘ use
    /// the device-dependent bits (NX_DEVICERALTKEYMASK 0x40, NX_DEVICERCMDKEYMASK 0x10), so the
    /// left-hand keys never count.
    func isDown(rawFlags: UInt) -> Bool {
        switch self {
        case .rightOption: return rawFlags & 0x40 != 0
        case .rightCommand: return rawFlags & 0x10 != 0
        case .fn: return rawFlags & NSEvent.ModifierFlags.function.rawValue != 0
        case .ctrlOptSpace: return false
        }
    }
}

/// The global talk key. Global monitors only receive key events once the app is trusted for
/// Accessibility; the local monitors cover the case where our own panel has focus.
@MainActor
final class Hotkey: ObservableObject {
    @Published private(set) var trusted = AXIsProcessTrusted()

    /// The chosen key in short form ("⌥ right", "⌃⌥Space").
    var hint: String { prefs.talkKey.hint }

    private var monitors: [Any] = []
    private var pollTimer: Timer?
    private var logic = TalkKeyLogic()
    private var keyDown = false
    private var bag = Set<AnyCancellable>()
    private let prefs: Prefs
    private let isTalking: @MainActor () -> Bool
    private let setTalk: @MainActor (Bool) -> Void

    /// `isTalking` reads the engine's talk state; `setTalk` asks the engine to change it.
    init(prefs: Prefs, isTalking: @escaping @MainActor () -> Bool, setTalk: @escaping @MainActor (Bool) -> Void) {
        self.prefs = prefs
        self.isTalking = isTalking
        self.setTalk = setTalk
        prefs.$talkKey.dropFirst()
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                guard let self else { return }
                self.keyDown = false
                self.objectWillChange.send()   // the hint changed
            }
            .store(in: &bag)
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
            installMonitors()  // re-add the global monitors so they start receiving events
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

    /// Both kinds of monitor stay installed; each checks the current choice, so changing the
    /// key needs no reinstall.
    private func installMonitors() {
        monitors.forEach(NSEvent.removeMonitor)
        monitors.removeAll()
        let flags: (NSEvent) -> Void = { [weak self] event in
            let code = event.keyCode, raw = event.modifierFlags.rawValue
            MainActor.assumeIsolated { self?.flagsChanged(keyCode: code, rawFlags: raw) }
        }
        if let g = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: flags) { monitors.append(g) }
        if let l = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged, handler: { event in
            flags(event)
            return event   // modifiers are never swallowed
        }) { monitors.append(l) }
        if let g = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: { [weak self] event in
            guard Self.isCtrlOptSpace(event) else { return }
            MainActor.assumeIsolated { self?.spacePressed() }
        }) { monitors.append(g) }
        if let l = NSEvent.addLocalMonitorForEvents(matching: .keyDown, handler: { [weak self] event in
            guard Self.isCtrlOptSpace(event) else { return event }
            let handled = MainActor.assumeIsolated { () -> Bool in
                guard let self, self.prefs.talkKey == .ctrlOptSpace else { return false }
                self.spacePressed()
                return true
            }
            return handled ? nil : event
        }) { monitors.append(l) }
    }

    private func flagsChanged(keyCode: UInt16, rawFlags: UInt) {
        let key = prefs.talkKey
        guard key.isModifier, keyCode == key.keyCode else { return }
        let down = key.isDown(rawFlags: rawFlags)
        guard down != keyDown else { return }   // repeated flag events for the same state
        keyDown = down
        let now = ProcessInfo.processInfo.systemUptime
        if down {
            logic.sync(isTalking())
            setTalk(logic.press(at: now))
        } else {
            setTalk(logic.release(at: now))   // a repeat of the current state is harmless
        }
    }

    private func spacePressed() {
        guard prefs.talkKey == .ctrlOptSpace else { return }
        setTalk(!isTalking())
    }

    nonisolated private static func isCtrlOptSpace(_ event: NSEvent) -> Bool {
        guard event.keyCode == TalkKey.ctrlOptSpace.keyCode, !event.isARepeat else { return false }
        let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            .subtracting([.capsLock, .numericPad, .function])
        return mods == [.control, .option]
    }
}
