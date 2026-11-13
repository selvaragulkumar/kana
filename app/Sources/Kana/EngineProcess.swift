import AppKit
import Foundation

/// Names that identify the app on disk and in the environment, in one place.
enum AppID {
    /// Folder under ~/Library/Application Support.
    static let supportFolder = "kana"
    /// Override command for the engine (testing hook).
    static let engineCommandEnv = ["KANA_ENGINE_CMD"]
    /// The engine package, launched with `python -m`.
    static let engineModule = "kana"
}

/// Where the engine lives and how to launch it. Lookup order:
/// 1. a checkout chosen in Setup (`~/Library/Application Support/<app>/engine_path`), when the
///    user picked it over the bundled engine (defaults key `engineUseCheckout`) or when the app
///    has no bundled engine (built from source with `build.sh --install`),
/// 2. the bundled engine, `Contents/Resources/engine/python/bin/python3` (DMG builds),
/// 3. the repo the running binary was built in (`<repo>/app/build/…` or `<repo>/app/.build/…`),
/// 4. none: Setup shows "Engine not found" with a folder picker.
enum EngineLocation {
    /// A resolved engine: the interpreter that runs `-m kana`, and the folder it runs in.
    struct Resolved: Equatable {
        let python: URL
        let root: URL
        let bundled: Bool
    }

    static let useCheckoutKey = "engineUseCheckout"

    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent(AppID.supportFolder, isDirectory: true)
    }

    static var engineFile: URL { supportDir.appendingPathComponent("engine_path") }

    /// `Contents/Resources/engine` when this app carries its own Python runtime.
    static var bundledRoot: URL? {
        guard let dir = Bundle.main.resourceURL?.appendingPathComponent("engine", isDirectory: true),
              FileManager.default.isExecutableFile(atPath: bundledPython(dir).path) else { return nil }
        return dir
    }

    private static func bundledPython(_ dir: URL) -> URL { dir.appendingPathComponent("python/bin/python3") }

    /// Python version of the bundled engine, from its VERSION file ("3.13.18 20261110 arm64").
    static var bundledVersion: String? {
        guard let dir = bundledRoot,
              let raw = try? String(contentsOf: dir.appendingPathComponent("VERSION"), encoding: .utf8) else { return nil }
        return raw.split(separator: " ").first.map(String.init)
    }

    /// The checkout recorded in engine_path, if any.
    static var checkoutRoot: URL? {
        guard let raw = try? String(contentsOf: engineFile, encoding: .utf8) else { return nil }
        let path = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else { return nil }
        return URL(fileURLWithPath: (path as NSString).expandingTildeInPath, isDirectory: true)
    }

    /// The user picked a checkout over the bundled engine (Setup › Engine).
    static var prefersCheckout: Bool {
        get { UserDefaults.standard.bool(forKey: useCheckoutKey) }
        set { UserDefaults.standard.set(newValue, forKey: useCheckoutKey) }
    }

    static var resolved: Resolved? {
        let bundled = bundledRoot
        if let checkout = checkoutRoot, prefersCheckout || bundled == nil {
            return Resolved(python: checkout.appendingPathComponent(".venv/bin/python"), root: checkout, bundled: false)
        }
        if let bundled {
            // The bundle is read-only and signed: the engine runs in the support folder.
            return Resolved(python: bundledPython(bundled), root: supportDir, bundled: true)
        }
        let exe = Bundle.main.executableURL?.resolvingSymlinksInPath().path ?? ""
        for marker in ["/app/build/", "/app/.build/"] {
            if let r = exe.range(of: marker) {
                let repo = URL(fileURLWithPath: String(exe[..<r.lowerBound]), isDirectory: true)
                return Resolved(python: repo.appendingPathComponent(".venv/bin/python"), root: repo, bundled: false)
            }
        }
        return nil
    }

    /// The engine folder: a checkout, or the support folder for the bundled engine. `.env` lives here.
    static var root: URL? { resolved?.root }

    /// An engine can be launched.
    static var found: Bool {
        if overrideCommand != nil { return true }
        guard let r = resolved else { return false }
        return r.bundled || usable(r.root)
    }

    /// Validates a chosen folder (has `.venv/bin/python` and an engine package), records it and
    /// uses it from now on, also over a bundled engine.
    static func choose(_ folder: URL) throws {
        guard usable(folder) else { throw EngineError.notAnEngine(folder.path) }
        try FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        try (folder.path + "\n").write(to: engineFile, atomically: true, encoding: .utf8)
        prefersCheckout = true
    }

    static func usable(_ folder: URL) -> Bool {
        FileManager.default.isExecutableFile(atPath: folder.appendingPathComponent(".venv/bin/python").path)
            && isDirectory(folder.appendingPathComponent(AppID.engineModule))
    }


    private static func isDirectory(_ url: URL) -> Bool {
        var d: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.path, isDirectory: &d) && d.boolValue
    }

    /// Override command, e.g. `python3 /path/to/fake_engine.py`. Testing hook.
    static var overrideCommand: String? {
        let env = ProcessInfo.processInfo.environment
        for name in AppID.engineCommandEnv {
            if let cmd = env[name]?.trimmingCharacters(in: .whitespacesAndNewlines), !cmd.isEmpty { return cmd }
        }
        return nil
    }

    /// Builds a Process for the engine with the given extra arguments. Throws a readable error
    /// when no engine is found.
    static func makeProcess(arguments: [String], extraEnv: [String: String] = [:]) throws -> Process {
        let p = Process()
        let resolved = self.resolved
        var env = ProcessInfo.processInfo.environment
        if let cmd = overrideCommand {
            // `sh -c '<cmd> "$@"' name args...` keeps the override's own quoting and appends ours.
            p.executableURL = URL(fileURLWithPath: "/bin/sh")
            p.arguments = ["-c", "exec \(cmd) \"$@\"", "engine"] + arguments
        } else {
            guard let resolved else { throw EngineError.notFound }
            guard FileManager.default.isExecutableFile(atPath: resolved.python.path) else {
                throw EngineError.missingPython(resolved.python.path)
            }
            p.executableURL = resolved.python
            p.arguments = ["-m", AppID.engineModule] + arguments
            if resolved.bundled {
                // Self-contained: nothing from the user's own Python setup leaks in, and no
                // bytecode is written into the signed bundle (it ships precompiled).
                for name in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "VIRTUAL_ENV"] {
                    env.removeValue(forKey: name)
                }
                env["PYTHONNOUSERSITE"] = "1"
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                env["PYTHONSAFEPATH"] = "1"
                try? FileManager.default.createDirectory(at: resolved.root, withIntermediateDirectories: true)
            }
        }
        if let root = resolved?.root, isDirectory(root) { p.currentDirectoryURL = root }
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        for name in AppID.engineCommandEnv { env.removeValue(forKey: name) }
        env.merge(extraEnv) { _, new in new }
        p.environment = env
        return p
    }

    /// One line for Setup › Engine.
    static var summary: String {
        if overrideCommand != nil { return "An override command is in use." }
        guard let r = resolved else { return "Choose the folder that holds the engine (.venv and the kana package)." }
        if r.bundled { return "Built in" + (bundledVersion.map { " (Python \($0))" } ?? "") + "." }
        return usable(r.root) ? r.root.path : "No engine in \(r.root.path)."
    }
}

enum EngineError: LocalizedError {
    case missingPython(String)
    case badDeviceList(String)
    case notFound
    case notAnEngine(String)

    var errorDescription: String? {
        switch self {
        case .missingPython(let path): return "Engine not found: \(path)"
        case .notFound: return "Engine not found. Choose its folder in Setup."
        case .notAnEngine(let path): return "\(path) has no .venv/bin/python with the engine package."
        case .badDeviceList(let detail): return "Could not list devices: \(detail)"
        }
    }
}

/// Splits a byte stream into lines. Used from a FileHandle's serial readability queue only.
private final class LineSplitter: @unchecked Sendable {
    private var buffer = Data()
    private let onLine: @Sendable (String) -> Void

    init(onLine: @escaping @Sendable (String) -> Void) { self.onLine = onLine }

    func feed(_ data: Data) {
        buffer.append(data)
        while let nl = buffer.firstIndex(of: 0x0A) {
            let lineData = buffer[buffer.startIndex..<nl]
            buffer.removeSubrange(buffer.startIndex...nl)
            if let line = String(data: lineData, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines), !line.isEmpty {
                onLine(line)
            }
        }
    }

    func flush() {
        if let line = String(data: buffer, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines), !line.isEmpty {
            onLine(line)
        }
        buffer.removeAll()
    }
}

/// Keeps the last few KB of stderr so an unexpected exit can be explained in the panel.
private final class TailBuffer: @unchecked Sendable {
    private var data = Data()
    private let lock = NSLock()

    func append(_ chunk: Data) {
        lock.lock(); defer { lock.unlock() }
        data.append(chunk)
        if data.count > 4096 { data = data.suffix(4096) }
    }

    var lastLine: String? {
        lock.lock(); defer { lock.unlock() }
        let text = String(decoding: data, as: UTF8.self)
        return text.split(whereSeparator: \.isNewline).last.map(String.init)
    }
}

/// The engine child process and everything the panel shows about it.
@MainActor
final class EngineProcess: ObservableObject {
    static let maxRows = 200

    // Lifecycle
    @Published private(set) var running = false
    @Published private(set) var ready = false
    @Published private(set) var talking = false
    @Published private(set) var startedAt: Date?

    // Live data
    @Published private(set) var rows: [TranscriptRow] = []
    @Published private(set) var inState: SessionState = .none
    @Published private(set) var outState: SessionState = .none
    @Published private(set) var usd: Double = 0
    @Published private(set) var lastError: String?
    @Published private(set) var lastErrorFatal = false
    @Published private(set) var model: String?
    /// Running median onset-to-audio latency per direction ("in"/"out"), from the audio tick.
    @Published private(set) var latencyMs: [String: Double] = [:]
    /// Seconds not sent thanks to voice-activity gating, per direction.
    @Published private(set) var gatedS: [String: Double] = [:]
    /// Last per-utterance latency event per direction: (onset→audio, src final→dst final), ms.
    @Published private(set) var lastUtterance: [String: (Double?, Double?)] = [:]
    /// Set when a start fails with a device problem; the panel opens Setup.
    @Published var needsSetup = false

    // Devices
    @Published private(set) var inputs: [AudioDevice] = []
    @Published private(set) var outputs: [AudioDevice] = []
    @Published private(set) var devicesError: String?
    @Published private(set) var loadingDevices = false
    /// The device list came from the fake engine.
    @Published private(set) var devicesAreFake = false

    /// The fake test engine is in use (its `ready` model or its device list says so).
    var isFakeEngine: Bool { model == "fake" || devicesAreFake }

    private var process: Process?
    private var stdinHandle: FileHandle?
    private var audioByDir: [String: (sent: Double, recv: Double)] = [:]
    /// Cost the engine computed from server-reported tokens, per direction.
    private var engineUsdByDir: [String: Double] = [:]
    /// Directions whose engine cost is itself an estimate (`est`: OpenAI, priced from audio sent).
    private var engineEstDirs: Set<String> = []
    /// True until the engine reports a cost; the footer then shows a seconds-based estimate.
    @Published private(set) var costIsEstimate = true

    /// Engine figures once any arrived; before that a seconds-based estimate (25 tokens per
    /// audio second, $3.50 / 1M in, $21 / 1M out), shown with "est.".
    private func recomputeCost() {
        if !engineUsdByDir.isEmpty {
            costIsEstimate = !engineEstDirs.isEmpty
            usd = engineUsdByDir.values.reduce(0, +)
        } else {
            costIsEstimate = true
            usd = audioByDir.values.reduce(0) { $0 + $1.sent * 0.0000875 + $1.recv * 0.000525 }
        }
    }
    static let jpyPerUSD = 150.0
    private var sawFatal = false
    private var stopRequested = false

    /// From `ready`: models per direction (nil = direction not running) and the register.
    @Published private(set) var inModel: String?
    @Published private(set) var outModel: String?
    @Published private(set) var register: String?

    /// Chip text derived from `ready`: nothing for the default model.
    var engineChip: String? {
        guard let m = model else { return nil }
        if m == "fake" { return "fake engine" }
        if m == "gemini-3.8-live" { return "fallback model" }
        if m.hasPrefix("gpt-") { return "OpenAI" }
        return nil
    }

    /// Tooltip for the engine chip: model per direction and what the register means.
    var engineTooltip: String {
        var lines: [String] = []
        lines.append("IN: \(inModel ?? "not running")")
        lines.append("OUT: \(outModel ?? "not running")")
        if inModel?.hasPrefix("gpt-") == true || outModel?.hasPrefix("gpt-") == true {
            lines.append("OpenAI: faster start, a voice adapted to the speaker's tone (not yours), no business keigo.")
        } else if register == "business" {
            lines.append("Business keigo: the outbound Japanese uses a stock voice, not yours.")
        } else if register != nil {
            lines.append("Register mirrors yours; your own voice both ways.")
        }
        return lines.joined(separator: "\n")
    }

    // MARK: Mark state

    /// The header mark and menu-bar state, kept calm on purpose:
    /// idle = static; Start → connecting (quarter turns) until the sessions first connect;
    /// from then on the whole session is listening (slow breathe), even through reconnects
    /// (those show only as footer text); talking is shown by the talk bar and the menu-bar
    /// bracket, not the mark; fatal → error (one shake, then dimmed). The state changes at
    /// most once per 2 s.
    @Published private(set) var markState: MarkState = .idle
    private var markTimer: Timer?
    private var reachedLive = false
    private var markChangedAt = Date.distantPast
    private var markRecheck: DispatchWorkItem?
    static let markDebounce: TimeInterval = 2

    private func desiredMarkState() -> MarkState {
        if !running { return (lastErrorFatal && lastError != nil) ? .error : .idle }
        if !reachedLive && ready && sessionsConnected { reachedLive = true }
        return reachedLive ? .listening : .connecting
    }

    private func updateMarkState() {
        let new = desiredMarkState()
        guard new != markState else { return }
        let wait = Self.markDebounce - Date().timeIntervalSince(markChangedAt)
        if wait > 0 {
            if markRecheck == nil {
                let item = DispatchWorkItem { [weak self] in
                    MainActor.assumeIsolated {
                        self?.markRecheck = nil
                        self?.updateMarkState()
                    }
                }
                markRecheck = item
                DispatchQueue.main.asyncAfter(deadline: .now() + wait, execute: item)
            }
            return
        }
        markState = new
        markChangedAt = Date()
    }

    private var sessionsConnected: Bool {
        let needIn = inModel != nil || model == nil, needOut = outModel != nil || model == nil
        return (!needIn || inState == .connected) && (!needOut || outState == .connected)
            && (inState == .connected || outState == .connected)
    }

    private let prefs: Prefs
    init(prefs: Prefs) { self.prefs = prefs }

    /// Offscreen rendering only (`kana --render-intro`): fills the published state with demo
    /// data without starting a process.
    func loadPreview(rows: [TranscriptRow], running: Bool, live: Bool, talking: Bool = false,
                     inputs: [AudioDevice] = [], outputs: [AudioDevice] = [], fake: Bool = false) {
        self.rows = rows
        self.running = running
        self.ready = running
        self.talking = talking
        self.inState = live ? .connected : (running ? .connecting : .none)
        self.outState = self.inState
        self.inputs = inputs
        self.outputs = outputs
        self.devicesAreFake = fake
        self.model = fake ? "fake" : nil
        self.startedAt = running ? Date().addingTimeInterval(-768) : nil
        self.usd = running ? 0.31 : 0
        self.costIsEstimate = false
        self.latencyMs = live ? ["in": 1800, "out": 2100] : [:]
        self.markState = !running ? .idle : (live ? .listening : .connecting)
    }

    // MARK: Start / stop

    func start(mic: String?, spk: String?, inLang: String, outLang: String, business: Bool) {
        guard process == nil else { return }
        // OpenAI takes no instruction, so business keigo is Gemini-only; the engine refuses the combination.
        let openai = prefs.usesOpenAI
        var args = ["--json", "--in", inLang, "--out", outLang,
                    "--register", business && !openai ? "business" : "default"]
        if openai { args += ["--provider", "openai"] }
        if let mic, !mic.isEmpty { args += ["--mic", mic] }
        if let spk, !spk.isEmpty { args += ["--spk", spk] }
        if !prefs.saveTranscripts { args.append("--no-save") }

        // The Keychain key goes into the child's environment, never onto the command line.
        // Without it the engine falls back to .env (python-dotenv does not override).
        var extraEnv: [String: String] = [:]
        if openai {
            if let key = KeychainStore.read(account: KeychainStore.openaiAccount), !key.isEmpty {
                extraEnv["OPENAI_API_KEY"] = key
            }
        } else if let key = KeychainStore.read(account: KeychainStore.geminiAccount), !key.isEmpty {
            extraEnv["GEMINI_API_KEY"] = key
        }

        let p: Process
        do {
            p = try EngineLocation.makeProcess(arguments: args, extraEnv: extraEnv)
        } catch {
            showError(error.localizedDescription, fatal: true)
            needsSetup = true
            return
        }

        let outPipe = Pipe(), inPipe = Pipe(), errPipe = Pipe()
        p.standardOutput = outPipe
        p.standardInput = inPipe
        p.standardError = errPipe

        let splitter = LineSplitter { [weak self] line in
            Task { @MainActor in self?.handle(line: line) }
        }
        outPipe.fileHandleForReading.readabilityHandler = { h in
            let data = h.availableData
            if data.isEmpty {
                h.readabilityHandler = nil
                splitter.flush()
            } else {
                splitter.feed(data)
            }
        }
        let tail = TailBuffer()
        errPipe.fileHandleForReading.readabilityHandler = { h in
            let data = h.availableData
            if data.isEmpty { h.readabilityHandler = nil } else { tail.append(data) }
        }
        p.terminationHandler = { [weak self] proc in
            let status = proc.terminationStatus
            let reason = proc.terminationReason
            // Give the stdout reader a moment to deliver the last lines (bye / fatal error).
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                MainActor.assumeIsolated {
                    self?.didExit(proc, status: status, reason: reason, stderrTail: tail.lastLine)
                }
            }
        }

        // Reset per-run state.
        rows.removeAll()
        audioByDir.removeAll()
        engineUsdByDir.removeAll()
        engineEstDirs.removeAll()
        costIsEstimate = true
        inModel = nil
        outModel = nil
        register = nil
        reachedLive = false
        latencyMs.removeAll()
        gatedS.removeAll()
        lastUtterance.removeAll()
        needsSetup = false
        usd = 0
        lastError = nil
        lastErrorFatal = false
        sawFatal = false
        stopRequested = false
        ready = false
        talking = false
        model = nil
        inState = .none   // set by session events; a one-direction run leaves the other at –
        outState = .none

        do {
            try p.run()
        } catch {
            showError("Could not start engine: \(error.localizedDescription)", fatal: true)
            inState = .none; outState = .none
            return
        }
        process = p
        stdinHandle = inPipe.fileHandleForWriting
        running = true
        markTimer?.invalidate()
        markTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.updateMarkState() }
        }
        updateMarkState()
        startedAt = Date()
    }

    /// Asks the engine to quit, then terminates it if it does not exit in time.
    func stop() {
        guard let p = process else { return }
        stopRequested = true
        send(["cmd": "quit"])
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            if p.isRunning { p.terminate() }
        }
    }

    /// Synchronous stop used when the app quits.
    func stopForQuit() {
        guard let p = process else { return }
        stopRequested = true
        send(["cmd": "quit"])
        let deadline = Date().addingTimeInterval(1.5)
        while p.isRunning && Date() < deadline { usleep(50_000) }
        if p.isRunning { p.terminate() }
    }

    func setTalk(_ on: Bool) {
        guard running else { return }
        send(["cmd": "talk", "on": on])
    }

    func toggleTalk() { setTalk(!talking) }

    private func send(_ obj: [String: Any]) {
        guard let h = stdinHandle,
              var data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])
        else { return }
        data.append(0x0A)
        try? h.write(contentsOf: data)
    }

    private func didExit(_ p: Process, status: Int32, reason: Process.TerminationReason, stderrTail: String?) {
        guard p === process else { return }
        process = nil
        try? stdinHandle?.close()
        stdinHandle = nil
        running = false
        markTimer?.invalidate()
        markTimer = nil
        defer { updateMarkState() }
        ready = false
        talking = false
        startedAt = nil
        if inState != .none { inState = .closed }
        if outState != .none { outState = .closed }
        if !stopRequested && !sawFatal && !(reason == .exit && status == 0) {
            let detail = stderrTail.map { ": \($0)" } ?? ""
            let how = reason == .uncaughtSignal ? "was killed (signal \(status))" : "exited (code \(status))"
            showError("Engine \(how)\(detail)", fatal: true)
            if Self.isSetupProblem(detail) { needsSetup = true }
        }
    }

    /// Device and key problems that the Setup page can explain.
    static func isSetupProblem(_ text: String) -> Bool {
        let t = text.lowercased()
        return t.contains("device") || t.contains("blackhole") || t.contains("gemini_api_key")
    }

    private func showError(_ text: String, fatal: Bool) {
        lastError = text
        lastErrorFatal = fatal
    }

    func dismissError() { lastError = nil; updateMarkState() }

    // MARK: Events

    private func handle(line: String) {
        guard let data = line.data(using: .utf8),
              let e = try? JSONDecoder().decode(EngineEvent.self, from: data) else {
            return  // stdout is JSON-only by contract; ignore anything else
        }
        defer { updateMarkState() }
        switch e.ev {
        case "ready":
            ready = true
            model = e.model
            inModel = e.in_model
            outModel = e.out_model
            register = e.register
        case "talk":
            talking = e.on ?? false
        case "transcript":
            guard let dir = Direction(rawValue: e.dir ?? ""), let text = e.text, !text.isEmpty else { return }
            addTranscript(dir: dir, kind: e.kind ?? "src", text: text,
                          row: e.row, rowText: e.row_text, mergeInto: e.merge_into)
        case "session":
            let state = SessionState(rawValue: e.state ?? "") ?? .none
            if e.dir == "in" { inState = state } else if e.dir == "out" { outState = state }
            if let detail = e.detail, detail.hasPrefix("error") {
                showError("\(e.dir?.uppercased() ?? "") session \(state.rawValue): \(detail)", fatal: false)
            }
        case "audio":
            if let dir = e.dir {
                audioByDir[dir] = (e.sent_s ?? 0, e.recv_s ?? 0)
                if let u = e.usd { engineUsdByDir[dir] = u }
                if e.est == true { engineEstDirs.insert(dir) }
                recomputeCost()
                if let g = e.gated_s { gatedS[dir] = g }
                if let l = e.latency_ms { latencyMs[dir] = l }
            }
        case "usage":
            if let dir = e.dir, let u = e.usd {
                engineUsdByDir[dir] = u
                if e.est == true { engineEstDirs.insert(dir) }
                recomputeCost()
            }
        case "latency":
            if let dir = e.dir { lastUtterance[dir] = (e.onset_to_audio_ms, e.src_final_to_dst_final_ms) }
        case "saved":
            if let md = e.md, !md.isEmpty { prefs.lastTranscriptMD = md }
        case "error":
            let fatal = e.fatal ?? false
            if fatal { sawFatal = true }
            let text = e.text ?? "Unknown engine error"
            showError(text, fatal: fatal)
            if fatal && Self.isSetupProblem(text) { needsSetup = true }
        case "bye":
            break
        default:
            break
        }
    }

    /// Places a transcript line. The engine pairs sources with translations (kana/pairing.py)
    /// and names the row: `row` is the row in this direction, `row_text` that side of it after
    /// the change, and `merge_into` means row `row` was folded into another row.
    /// Events without `row` (an older engine) open or fill rows in order.
    private func addTranscript(dir: Direction, kind: String, text: String,
                               row: Int?, rowText: String?, mergeInto: Int?) {
        guard let row else { return addTranscriptInOrder(dir: dir, kind: kind, text: text) }
        if let into = mergeInto {
            rows.removeAll { $0.dir == dir && $0.key == row }
            if let i = rows.firstIndex(where: { $0.dir == dir && $0.key == into }) {
                rows[i].src = rowText ?? joined(rows[i].src, text)
                rows[i].updatedAt = Date()
            }
            return
        }
        if let i = rows.firstIndex(where: { $0.dir == dir && $0.key == row }) {
            if kind == "dst" {
                rows[i].dst = rowText ?? joined(rows[i].dst, text)
            } else {
                rows[i].src = rowText ?? joined(rows[i].src, text)
            }
            rows[i].updatedAt = Date()
        } else {
            let side = rowText ?? text
            rows.append(TranscriptRow(dir: dir, src: kind == "dst" ? "" : side, dst: kind == "dst" ? side : "",
                                      key: row))
        }
        trimRows()
    }

    private func joined(_ a: String, _ b: String) -> String { a.isEmpty ? b : a + " " + b }

    private func trimRows() {
        if rows.count > Self.maxRows { rows.removeFirst(rows.count - Self.maxRows) }
    }

    /// Fallback for events without row ids: a `src` opens a row; a `dst` fills the oldest row
    /// in that direction still missing its translation.
    private func addTranscriptInOrder(dir: Direction, kind: String, text: String) {
        if kind == "dst" {
            if let i = rows.firstIndex(where: { $0.dir == dir && $0.dst.isEmpty }) {
                rows[i].dst = text
                rows[i].updatedAt = Date()
            } else {
                rows.append(TranscriptRow(dir: dir, src: "", dst: text))
            }
        } else {
            if let i = rows.lastIndex(where: { $0.dir == dir }), rows[i].src.isEmpty {
                rows[i].src = text
                rows[i].updatedAt = Date()
            } else {
                rows.append(TranscriptRow(dir: dir, src: text, dst: ""))
            }
        }
        trimRows()
    }

    // MARK: Devices

    /// Offscreen rendering: never spawn the engine.
    static var previewMode = false

    func refreshDevices() {
        guard !loadingDevices, !Self.previewMode else { return }
        loadingDevices = true
        devicesError = nil
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Self.listDevices()
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    self.loadingDevices = false
                    switch result {
                    case .success(let list):
                        self.inputs = list.inputs
                        self.devicesAreFake = list.fake ?? false
                        self.outputs = list.outputs
                    case .failure(let err):
                        self.devicesError = err.localizedDescription
                    }
                }
            }
        }
    }

    nonisolated private static func listDevices() -> Result<DeviceList, Error> {
        do {
            let p = try EngineLocation.makeProcess(arguments: ["--list-devices", "--json"])
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err
            p.standardInput = FileHandle.nullDevice
            try p.run()
            // Read before waiting so a large output cannot block the child on a full pipe.
            let data = out.fileHandleForReading.readDataToEndOfFile()
            let errData = err.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            let text = String(decoding: data, as: UTF8.self)
            for line in text.split(whereSeparator: \.isNewline) {
                if let d = line.data(using: .utf8),
                   let list = try? JSONDecoder().decode(DeviceList.self, from: d) {
                    return .success(list)
                }
            }
            let errLine = String(decoding: errData, as: UTF8.self)
                .split(whereSeparator: \.isNewline).last.map(String.init)
            return .failure(EngineError.badDeviceList(errLine ?? "no JSON on stdout (exit \(p.terminationStatus))"))
        } catch {
            return .failure(error)
        }
    }
}
