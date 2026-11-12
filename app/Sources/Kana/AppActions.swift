import AppKit

/// Actions shared by the panel's menus and the status item's right-click menu.
@MainActor
final class AppActions: ObservableObject {
    /// Set to true to make the panel show its Setup page (from a menu, or a device error).
    @Published var setupRequested = false
    var showPanel: () -> Void = {}
    var hidePanel: () -> Void = {}

    private let prefs: Prefs
    init(prefs: Prefs) { self.prefs = prefs }

    /// The engine's default save folder (~/Library/Application Support/kana/transcripts).
    static var defaultTranscriptsFolder: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/kana/transcripts", isDirectory: true)
    }

    var lastTranscriptURL: URL? {
        guard let p = prefs.lastTranscriptMD, FileManager.default.fileExists(atPath: p) else { return nil }
        return URL(fileURLWithPath: p)
    }

    var transcriptsFolder: URL {
        lastTranscriptURL?.deletingLastPathComponent() ?? Self.defaultTranscriptsFolder
    }

    func openLastTranscript() {
        if let url = lastTranscriptURL { NSWorkspace.shared.open(url) }
    }

    func openTranscriptsFolder() {
        let folder = transcriptsFolder
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        NSWorkspace.shared.open(folder)
    }

    func openSetup() {
        setupRequested = true
        showPanel()
    }

    // MARK: NSMenu helpers with closures

    private var handlers: [ClosureTarget] = []

    func menuItem(_ title: String, state: Bool? = nil, action: @escaping () -> Void) -> NSMenuItem {
        let target = ClosureTarget(action)
        handlers.append(target)
        if handlers.count > 64 { handlers.removeFirst(handlers.count - 64) }
        let item = NSMenuItem(title: title, action: #selector(ClosureTarget.fire), keyEquivalent: "")
        item.target = target
        if let state { item.state = state ? .on : .off }
        return item
    }
}

final class ClosureTarget: NSObject {
    private let action: () -> Void
    init(_ action: @escaping () -> Void) { self.action = action }
    @objc func fire() { action() }
}
