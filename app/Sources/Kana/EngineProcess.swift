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
/// 1. `~/Library/Application Support/<app>/engine_path` (written by Setup's folder picker),
/// 2. `Contents/Resources/engine/` inside the app bundle (a future bundled engine),
/// 3. the repo the running binary was built in (`<repo>/app/build/…` or `<repo>/app/.build/…`),
/// 4. none: Setup shows "Engine not found" with a folder picker.
enum EngineLocation {
    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent(AppID.supportFolder, isDirectory: true)
    }

    static var engineFile: URL { supportDir.appendingPathComponent("engine_path") }

    static var root: URL? {
        if let raw = try? String(contentsOf: engineFile, encoding: .utf8) {
            let path = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !path.isEmpty {
                return URL(fileURLWithPath: (path as NSString).expandingTildeInPath, isDirectory: true)
            }
        }
        if let bundled = Bundle.main.resourceURL?.appendingPathComponent("engine", isDirectory: true),
           isDirectory(bundled) {
            return bundled
        }
        let exe = Bundle.main.executableURL?.resolvingSymlinksInPath().path ?? ""
        for marker in ["/app/build/", "/app/.build/"] {
            if let r = exe.range(of: marker) {
                return URL(fileURLWithPath: String(exe[..<r.lowerBound]), isDirectory: true)
            }
        }
        return nil
    }

    /// Validates a chosen folder (has `.venv/bin/python` and an engine package) and records it.
    static func choose(_ folder: URL) throws {
        guard usable(folder) else { throw EngineError.notAnEngine(folder.path) }
        try FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
        try (folder.path + "\n").write(to: engineFile, atomically: true, encoding: .utf8)
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
        let root = self.root
        if let cmd = overrideCommand {
            // `sh -c '<cmd> "$@"' name args...` keeps the override's own quoting and appends ours.
            p.executableURL = URL(fileURLWithPath: "/bin/sh")
            p.arguments = ["-c", "exec \(cmd) \"$@\"", "engine"] + arguments
        } else {
            guard let root else { throw EngineError.notFound }
            let python = root.appendingPathComponent(".venv/bin/python")
            guard FileManager.default.isExecutableFile(atPath: python.path) else {
                throw EngineError.missingPython(python.path)
            }
            p.executableURL = python
            p.arguments = ["-m", AppID.engineModule] + arguments
        }
        if let root, isDirectory(root) { p.currentDirectoryURL = root }
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        for name in AppID.engineCommandEnv { env.removeValue(forKey: name) }
        env.merge(extraEnv) { _, new in new }
        p.environment = env
        return p
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

    private var process: Process?
    private var stdinHandle: FileHandle?
    private var audioByDir: [String: (sent: Double, recv: Double)] = [:]
    /// Cost the engine computed from server-reported tokens, per direction.
    private var engineUsdByDir: [String: Double] = [:]
    /// True until the engine reports a cost; the footer then shows a seconds-based estimate.
    @Published private(set) var costIsEstimate = true

    /// Engine figures once any arrived; before that a seconds-based estimate (25 tokens per
    /// audio second, $3.50 / 1M in, $21 / 1M out), shown with "est.".
    private func recomputeCost() {
        if !engineUsdByDir.isEmpty {
            costIsEstimate = false
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
        return nil
    }

    /// Tooltip for the engine chip: model per direction and what the register means.
    var engineTooltip: String {
        var lines: [String] = []
        lines.append("IN: \(inModel ?? "not running")")
        lines.append("OUT: \(outModel ?? "not running")")
        if register == "business" {
            lines.append("Business keigo: the outbound Japanese uses a stock voice, not yours.")
        } else if register != nil {
            lines.append("Register mirrors yours; your own voice both ways.")
        }
        return lines.joined(separator: "\n")
    }

    // MARK: Mark state

    /// The header mark and menu-bar state. Start → connecting; all running sessions connected →
    /// listening; talk on → talking; translated audio arriving → translating; fatal → error.
    @Published private(set) var markState: MarkState = .idle
    private var lastTranslatedAt: Date?
    private var markTimer: Timer?

    private func updateMarkState() {
        let new: MarkState
        if !running {
            new = (lastErrorFatal && lastError != nil) ? .error : .idle
        } else if talking {
            new = .talking
        } else if !ready || !sessionsConnected {
            new = .connecting
        } else if let t = lastTranslatedAt, Date().timeIntervalSince(t) < 1.5 {
            new = .translating
        } else {
            new = .listening
        }
        if new != markState { markState = new }
    }

    private var sessionsConnected: Bool {
        let needIn = inModel != nil || model == nil, needOut = outModel != nil || model == nil
        return (!needIn || inState == .connected) && (!needOut || outState == .connected)
            && (inState == .connected || outState == .connected)
    }

    private func noteTranslated() {
        lastTranslatedAt = Date()
        updateMarkState()
    }

    private let prefs: Prefs
    init(prefs: Prefs) { self.prefs = prefs }

    // MARK: Start / stop

    func start(mic: String?, spk: String?, inLang: String, outLang: String, business: Bool) {
        guard process == nil else { return }
        var args = ["--json", "--in", inLang, "--out", outLang, "--register", business ? "business" : "default"]
        if let mic, !mic.isEmpty { args += ["--mic", mic] }
        if let spk, !spk.isEmpty { args += ["--spk", spk] }
        if !prefs.saveTranscripts { args.append("--no-save") }

        // The Keychain key goes into the child's environment, never onto the command line.
        // Without it the engine falls back to .env (python-dotenv does not override).
        var extraEnv: [String: String] = [:]
        if let key = KeychainStore.read(account: KeychainStore.geminiAccount), !key.isEmpty {
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
        costIsEstimate = true
        inModel = nil
        outModel = nil
        register = nil
        lastTranslatedAt = nil
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
            addTranscript(dir: dir, kind: e.kind ?? "src", text: text)
            if e.kind == "dst" { noteTranslated() }
        case "session":
            let state = SessionState(rawValue: e.state ?? "") ?? .none
            if e.dir == "in" { inState = state } else if e.dir == "out" { outState = state }
            if let detail = e.detail, detail.hasPrefix("error") {
                showError("\(e.dir?.uppercased() ?? "") session \(state.rawValue): \(detail)", fatal: false)
            }
        case "audio":
            if let dir = e.dir {
                if (e.recv_s ?? 0) > (audioByDir[dir]?.recv ?? 0) { noteTranslated() }
                audioByDir[dir] = (e.sent_s ?? 0, e.recv_s ?? 0)
                if let u = e.usd { engineUsdByDir[dir] = u }
                recomputeCost()
                if let g = e.gated_s { gatedS[dir] = g }
                if let l = e.latency_ms { latencyMs[dir] = l }
            }
        case "usage":
            if let dir = e.dir, let u = e.usd { engineUsdByDir[dir] = u; recomputeCost() }
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

    /// Pairs source and translation lines into rows. A `src` opens a row in its direction;
    /// a `dst` fills the oldest row in that direction still missing its translation.
    private func addTranscript(dir: Direction, kind: String, text: String) {
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
        if rows.count > Self.maxRows { rows.removeFirst(rows.count - Self.maxRows) }
    }

    // MARK: Devices

    func refreshDevices() {
        guard !loadingDevices else { return }
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
