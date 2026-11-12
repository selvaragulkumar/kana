import AppKit
import Combine

/// App-wide switches, persisted in UserDefaults. The language pair and devices stay in
/// `@AppStorage` inside the panel (same defaults domain).
@MainActor
final class Prefs: ObservableObject {
    static let shared = Prefs()
    private let d = UserDefaults.standard

    /// Off by default: our windows are left out of screen shares and recordings.
    @Published var visibleInShare: Bool {
        didSet { d.set(visibleInShare, forKey: "visibleInShare"); WindowPrivacy.applyAll() }
    }
    @Published var captionsOn: Bool {
        didSet { d.set(captionsOn, forKey: "captionsOn") }
    }
    @Published var saveTranscripts: Bool {
        didSet { d.set(saveTranscripts, forKey: "saveTranscripts") }
    }
    /// The panel is collapsed into the floating bar; kept across launches.
    @Published var minimized: Bool {
        didSet { d.set(minimized, forKey: "minimized") }
    }
    /// Paths from the engine's last `saved` event, kept across launches.
    @Published var lastTranscriptMD: String? {
        didSet { d.set(lastTranscriptMD, forKey: "lastTranscriptMD") }
    }

    private init() {
        visibleInShare = d.bool(forKey: "visibleInShare")
        captionsOn = d.object(forKey: "captionsOn") as? Bool ?? false   // off until the user turns it on
        saveTranscripts = d.object(forKey: "saveTranscripts") as? Bool ?? true
        lastTranscriptMD = d.string(forKey: "lastTranscriptMD")
        minimized = d.bool(forKey: "minimized")
    }
}

/// Applies the screen-share preference to our windows. `.none` keeps a window out of
/// screenshots, screen recordings and screen sharing; `.readOnly` is the normal behaviour.
@MainActor
enum WindowPrivacy {
    static func apply(_ window: NSWindow) {
        // The status-bar item lives in the system menu bar; leave that one alone.
        guard !String(describing: type(of: window)).contains("StatusBar") else { return }
        window.sharingType = Prefs.shared.visibleInShare ? .readOnly : .none
    }

    static func applyAll() {
        NSApp?.windows.forEach(apply)
    }

    /// Catches windows created later (the menu-bar panel is created lazily on first open).
    static func observe() {
        let nc = NotificationCenter.default
        for name in [NSWindow.didBecomeKeyNotification, NSWindow.didBecomeMainNotification] {
            nc.addObserver(forName: name, object: nil, queue: .main) { note in
                guard let w = note.object as? NSWindow else { return }
                MainActor.assumeIsolated {
                    let want: NSWindow.SharingType = Prefs.shared.visibleInShare ? .readOnly : .none
                    if w.sharingType != want { apply(w) }
                }
            }
        }
    }
}
