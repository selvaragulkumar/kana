import AppKit
import SwiftUI

@main
struct KanaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    // All windows are AppKit-owned (status item panel, caption strip); SwiftUI needs a scene.
    var body: some Scene {
        Settings { EmptyView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var engine: EngineProcess!
    private var hotkey: Hotkey!
    private var actions: AppActions!
    private var status: StatusController!
    private var captions: CaptionController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Writing to a dead engine's stdin must not kill the app.
        signal(SIGPIPE, SIG_IGN)
        Theme.registerFonts()
        // `kana --render-marks <dir>`: write stills of the six mark states and exit (docs, tests).
        if let i = CommandLine.arguments.firstIndex(of: "--render-marks"), i + 1 < CommandLine.arguments.count {
            MarkStills.render(to: URL(fileURLWithPath: CommandLine.arguments[i + 1]))
            exit(0)
        }
        // `kana --render-intro <dir>`: intro, panel, bar and transition frames, offscreen.
        if let i = CommandLine.arguments.firstIndex(of: "--render-intro"), i + 1 < CommandLine.arguments.count {
            IntroRender.run(to: URL(fileURLWithPath: CommandLine.arguments[i + 1]))
            exit(0)
        }
        WindowPrivacy.observe()

        let prefs = Prefs.shared
        let engine = EngineProcess(prefs: prefs)
        let hotkey = Hotkey { [weak engine] in engine?.toggleTalk() }
        let actions = AppActions(prefs: prefs)
        self.engine = engine
        self.hotkey = hotkey
        self.actions = actions
        status = StatusController(engine: engine, hotkey: hotkey, prefs: prefs, actions: actions)
        captions = CaptionController(engine: engine, prefs: prefs)
        hotkey.install()
        engine.refreshDevices()
        status.launch()
        installTestHooks()
    }

    /// `KANA_TEST_HOOKS=1` only: drive the UI from scripts (screen recordings, smoke tests) with
    /// distributed notifications named "kana.test", object = open|start|stop|talk|minimize|expand|close.
    private func installTestHooks() {
        guard ProcessInfo.processInfo.environment["KANA_TEST_HOOKS"] == "1" else { return }
        DistributedNotificationCenter.default().addObserver(forName: Notification.Name("kana.test"), object: nil, queue: .main) { [weak self] note in
            let cmd = note.object as? String ?? ""
            MainActor.assumeIsolated {
                guard let self else { return }
                switch cmd {
                case "open": self.status.show()
                case "start":
                    let d = UserDefaults.standard
                    self.engine.start(mic: d.string(forKey: "mic"), spk: d.string(forKey: "spk"),
                                      inLang: d.string(forKey: "inLang") ?? "en", outLang: d.string(forKey: "outLang") ?? "ja",
                                      business: d.bool(forKey: "businessKeigo"))
                case "stop": self.engine.stop()
                case "talk": self.engine.toggleTalk()
                case "minimize": self.status.minimize()
                case "expand": self.status.expand()
                case "close": self.status.hide()
                default: break
                }
            }
        }
    }

    /// Launching kana again (Spotlight, Finder, Launchpad) while it runs opens the panel.
    /// A menu-bar-only app has no Dock icon, and its status item can sit hidden behind the
    /// notch when the frontmost app has many menus, so this is the reliable way back in.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        status?.reopen()
        return false
    }

    func applicationWillTerminate(_ notification: Notification) {
        engine?.stopForQuit()
    }
}

/// Renders the six mark states as PNGs (one still per state at a characteristic moment, plus
/// a strip), with ImageRenderer, so the motion can be checked without screen capture.
@MainActor
enum MarkStills {
    /// Time into each state that shows its motion: mid-step, mid-breathe, mid-pulse, mid-trace, mid-shake.
    static let moments: [MarkState: [Double]] = [
        .idle: [0], .connecting: [0, 0.45, 0.85, 1.25], .listening: [0, 0.6, 1.2],
        .talking: [0, 0.23, 0.46], .translating: [0.2, 0.5, 0.75, 1.0, 1.4, 1.7], .error: [0.1, 0.3, 1.0],
    ]

    static func render(to dir: URL) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        for state in MarkState.allCases {
            let frames = moments[state] ?? [0]
            let view = HStack(spacing: 24) {
                ForEach(Array(frames.enumerated()), id: \.offset) { _, t in
                    VStack(spacing: 8) {
                        KanaMark(state: state, size: 96, fixedTime: t)
                        Text(String(format: "%.2f s", t)).font(Theme.ui(11)).foregroundStyle(Theme.text4)
                    }
                }
            }
            .padding(28)
            .background(Theme.bg)
            write(view, to: dir.appendingPathComponent("mark-\(state.rawValue).png"))
        }
        let strip = HStack(spacing: 16) {
            ForEach(MarkState.allCases, id: \.self) { state in
                VStack(spacing: 14) {
                    KanaMark(state: state, size: 96, fixedTime: (moments[state] ?? [0]).dropFirst().first ?? 0)
                        .frame(width: 120, height: 120)
                    Text(state.rawValue).font(Theme.ui(14, 600)).foregroundStyle(Theme.text)
                }
                .padding(.vertical, 24)
                .frame(width: 160)
                .background(RoundedRectangle(cornerRadius: 20).fill(Theme.c(0x0C0C0E)))
                .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(Theme.c(0x1E1E22)))
            }
        }
        .padding(32)
        .background(Theme.c(0x070708))
        write(strip, to: dir.appendingPathComponent("mark-states.png"))
        renderMenuBars(to: dir)
    }

    /// The menu-bar icon as the system shows it: the template tinted for a dark and a light bar,
    /// and the non-template talking variant drawn in each appearance.
    static func renderMenuBars(to dir: URL) {
        func bitmap(_ talking: Bool, dark: Bool) -> NSImage {
            let src = MenuIcon.image(talking: talking)
            let out = NSImage(size: NSSize(width: 18, height: 18))
            let appearance = NSAppearance(named: dark ? .darkAqua : .aqua)!
            appearance.performAsCurrentDrawingAppearance {
                out.lockFocus()
                src.draw(in: NSRect(x: 0, y: 0, width: 18, height: 18))
                if src.isTemplate {   // what the menu bar does with a template image
                    (dark ? NSColor.white : NSColor.black).set()
                    NSRect(x: 0, y: 0, width: 18, height: 18).fill(using: .sourceAtop)
                }
                out.unlockFocus()
            }
            return out
        }
        let bars = VStack(spacing: 12) {
            ForEach([true, false], id: \.self) { dark in
                HStack(spacing: 16) {
                    Spacer()
                    Text("Wi-Fi")
                    Image(nsImage: bitmap(false, dark: dark))
                    Image(nsImage: bitmap(true, dark: dark))
                    Text("Thu 20:05")
                }
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(dark ? Color.white : Color(white: 0.07))
                .padding(.horizontal, 14)
                .frame(width: 420, height: 28)
                .background(RoundedRectangle(cornerRadius: 8).fill(dark ? Theme.c(0x2A2A2E) : Theme.c(0xECECEE)))
            }
        }
        .padding(24)
        .background(Theme.c(0x0C0C0E))
        write(bars, to: dir.appendingPathComponent("menubar-dark-light.png"))
    }

    private static func write<V: View>(_ view: V, to url: URL) {
        let r = ImageRenderer(content: view.environment(\.colorScheme, .dark))
        r.scale = 2
        guard let cg = r.cgImage else { return }
        let rep = NSBitmapImageRep(cgImage: cg)
        try? rep.representation(using: .png, properties: [:])?.write(to: url)
    }
}
