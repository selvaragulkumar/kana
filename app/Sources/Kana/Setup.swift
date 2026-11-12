import AppKit
import AVFoundation
import SwiftUI

/// Live state for the Setup page: devices, permissions, key, engine.
@MainActor
final class SetupModel: ObservableObject {
    static let brewLine = "brew install --cask blackhole-2ch blackhole-16ch"

    @Published private(set) var devices: [CADevice] = []
    @Published private(set) var keySource: KeySource = .missing
    @Published private(set) var micStatus: AVAuthorizationStatus = .notDetermined
    @Published private(set) var engineFound = false
    @Published private(set) var engineRoot: URL?
    @Published var engineMessage: String?

    /// Folder picker for the engine checkout; writes engine_path. The caller hides the panel
    /// first, because the panel floats above normal windows.
    func chooseEngineFolder() {
        let open = NSOpenPanel()
        open.canChooseDirectories = true
        open.canChooseFiles = false
        open.allowsMultipleSelection = false
        open.prompt = "Use This Folder"
        open.message = "Choose the folder that contains the engine (.venv and the kana package)."
        NSApp.activate(ignoringOtherApps: true)
        guard open.runModal() == .OK, let url = open.url else { return }
        do {
            try EngineLocation.choose(url)
            engineMessage = nil
        } catch {
            engineMessage = error.localizedDescription
        }
        refresh()
    }
    @Published private(set) var testing = false
    @Published private(set) var testResults: [LoopbackTester.Outcome] = []
    @Published var keyMessage: String?
    @Published var keyMessageOK = false

    var bh2: CADevice? { CoreAudioDevices.find("BlackHole 2ch", in: devices) }
    var bh16: CADevice? { CoreAudioDevices.find("BlackHole 16ch", in: devices) }
    var blackholeMissing: Bool { bh2 == nil || bh16 == nil }

    // First-launch steps, in order: drivers, key, permissions.
    var driversDone: Bool { !blackholeMissing }
    var keyDone: Bool { keySource != .missing }
    func permissionsDone(accessibility: Bool) -> Bool { micStatus == .authorized && accessibility }

    /// Something a new user must still do; the panel opens Setup by itself when true.
    func needsFirstRun(accessibility: Bool) -> Bool {
        !driversDone || !keyDone || micStatus != .authorized || !engineFound
            || (!accessibility && !UserDefaults.standard.bool(forKey: "setupSeen"))
    }

    func refresh() {
        guard !previewing else { return }
        devices = CoreAudioDevices.all()
        keySource = KeySource.current()
        micStatus = MicPermission.status
        engineRoot = EngineLocation.root
        engineFound = EngineLocation.found
        engineBundled = EngineLocation.bundledRoot != nil
        engineUsesCheckout = EngineLocation.resolved.map { !$0.bundled } ?? false
    }

    // MARK: Drivers

    enum InstallState: Equatable {
        case idle
        case working(String)
        case done(String)
        case needsRestart
        case failed(String)
    }

    @Published private(set) var install: InstallState = .idle
    @Published private(set) var engineBundled = false
    @Published private(set) var engineUsesCheckout = false

    var installing: Bool { if case .working = install { return true } else { return false } }

    /// One click: fetch + verify the missing BlackHole pkgs, one admin prompt, restart
    /// coreaudiod, then wait for the devices to show up.
    func installDrivers() {
        guard !installing else { return }
        let wanted = DriverInstaller.drivers.filter { CoreAudioDevices.find($0.name, in: devices) == nil }
        guard !wanted.isEmpty else { refresh(); return }
        install = .working(DriverInstaller.bundledDir == nil ? "Downloading from Existential Audio…" : "Preparing…")
        Task {
            do {
                let pkgs = try await DriverInstaller.fetch(wanted)
                install = .working("Waiting for your password…")
                try await DriverInstaller.runAdmin(pkgs)
                install = .working("Loading the drivers…")
                let ok = await DriverInstaller.waitForDevices(wanted.map(\.name))
                refresh()
                install = ok ? .done("Installed. No restart needed.") : .needsRestart
            } catch {
                install = .failed(error.localizedDescription)
                refresh()
            }
        }
    }

    // MARK: Engine choice

    /// Back to the engine inside the app (Setup › Engine › Use built-in).
    func useBundledEngine() {
        EngineLocation.prefersCheckout = false
        engineMessage = nil
        refresh()
    }

    /// Offscreen rendering only (`kana --render-setup`).
    func loadPreview(devices: [CADevice], key: KeySource, mic: AVAuthorizationStatus, install: InstallState) {
        self.devices = devices
        keySource = key
        micStatus = mic
        engineFound = true
        engineBundled = true
        self.install = install
        previewing = true
    }
    private var previewing = false

    // MARK: Devices

    func testDevices() {
        guard !testing else { return }
        testing = true
        testResults = []
        Task {
            if MicPermission.status == .notDetermined { _ = await MicPermission.request() }
            micStatus = MicPermission.status
            var results: [LoopbackTester.Outcome] = []
            for name in ["BlackHole 2ch", "BlackHole 16ch"] {
                if let d = CoreAudioDevices.find(name, in: CoreAudioDevices.all()) {
                    results.append(await LoopbackTester.run(device: d))
                } else {
                    results.append(.init(ok: false, text: "\(name) not installed"))
                }
                testResults = results
            }
            testing = false
        }
    }

    // MARK: Key

    func saveKey(_ key: String) {
        let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !k.isEmpty else { return }
        do {
            try KeychainStore.save(k, account: KeychainStore.geminiAccount)
            keyMessage = "Saved to the login Keychain."
            keyMessageOK = true
        } catch {
            keyMessage = error.localizedDescription
            keyMessageOK = false
        }
        refresh()
    }

    func removeKey() {
        KeychainStore.delete(account: KeychainStore.geminiAccount)
        keyMessage = "Removed from the Keychain."
        keyMessageOK = true
        refresh()
    }

    /// Uses the engine's `--check-key` when it has one (a real call to Google); otherwise only
    /// checks the format, and says so.
    func testKey(typed: String) {
        let typedKey = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = !typedKey.isEmpty ? typedKey
            : (KeychainStore.read(account: KeychainStore.geminiAccount) ?? KeySource.dotenvValue() ?? "")
        guard !key.isEmpty else {
            keyMessage = "No key to test."
            keyMessageOK = false
            return
        }
        keyMessage = "Testing…"
        Task.detached {
            let outcome = Self.checkWithEngine(key: key) ?? Self.formatCheck(key)
            await MainActor.run {
                self.keyMessage = outcome.text
                self.keyMessageOK = outcome.ok
            }
        }
    }

    nonisolated private static func formatCheck(_ key: String) -> LoopbackTester.Outcome {
        let ok = key.hasPrefix("AIza") && key.count >= 30
        let shape = "\(key.prefix(4))…, \(key.count) characters"
        return .init(ok: ok, text: ok
            ? "Format looks right (\(shape)). Not checked with Google: this engine has no --check-key."
            : "That does not look like a Gemini key (\(shape)); keys start with AIza.")
    }

    /// nil when the engine has no `--check-key` (or the fake engine is in use).
    nonisolated private static func checkWithEngine(key: String) -> LoopbackTester.Outcome? {
        guard EngineLocation.overrideCommand == nil else { return nil }
        guard let help = run(["--help"], key: nil, timeout: 10), help.out.contains("--check-key") else { return nil }
        guard let r = run(["--check-key"], key: key, timeout: 30) else {
            return .init(ok: false, text: "Key check timed out.")
        }
        let msg = (r.out + r.err).split(whereSeparator: \.isNewline).last.map(String.init) ?? ""
        return .init(ok: r.status == 0, text: r.status == 0
            ? "Key works (checked with Google). \(msg)"
            : "Key check failed: \(msg)")
    }

    nonisolated private static func run(_ args: [String], key: String?, timeout: TimeInterval)
        -> (status: Int32, out: String, err: String)? {
        guard let p = try? EngineLocation.makeProcess(arguments: args, extraEnv: key.map { ["GEMINI_API_KEY": $0] } ?? [:])
        else { return nil }
        let out = Pipe(), err = Pipe()
        p.standardOutput = out
        p.standardError = err
        p.standardInput = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return nil }
        let deadline = Date().addingTimeInterval(timeout)
        while p.isRunning && Date() < deadline { usleep(50_000) }
        if p.isRunning { p.terminate(); return nil }
        let o = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        let e = String(decoding: err.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        return (p.terminationStatus, o, e)
    }
}

/// The Setup page: every check is a card in the panel's warning pattern. A passing check is a
/// quiet surface card with a green tick; a failing one is the red-tinted alert card.
struct SetupView: View {
    @ObservedObject var model: SetupModel
    @EnvironmentObject private var hotkey: Hotkey
    @EnvironmentObject private var engine: EngineProcess
    @EnvironmentObject private var actions: AppActions
    var onDone: () -> Void

    @State private var keyField = ""
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                KanaMark(state: .idle, size: 24)
                Text("Setup").font(Theme.brand(20)).tracking(-0.4)
                Spacer()
                Button("Done", action: onDone).buttonStyle(PrimaryButtonStyle())
            }
            stepper
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    section("1  Audio drivers")
                    check(model.bh2 != nil, "BlackHole 2ch", model.bh2 != nil ? "Found. Meet's microphone." : "Missing. Meet's microphone.")
                    check(model.bh16 != nil, "BlackHole 16ch", model.bh16 != nil ? "Found. Meet's speakers." : "Missing. Meet's speakers.")
                    if model.blackholeMissing || model.install != .idle { installCard }
                    if !model.blackholeMissing { testCard }

                    section("2  Gemini API key")
                    check(model.keySource != .missing, model.keySource != .missing ? "Key found" : "No key", keySourceText)
                    keyCard

                    section("3  Permissions")
                    check(model.micStatus == .authorized, "Microphone", micText) {
                        if model.micStatus == .notDetermined {
                            Button("Allow") { Task { _ = await MicPermission.request(); model.refresh() } }
                                .buttonStyle(SmallButtonStyle())
                        } else if model.micStatus != .authorized {
                            Button("Open Settings") { openPrivacy("Privacy_Microphone") }
                                .buttonStyle(SmallButtonStyle())
                        }
                    }
                    check(hotkey.trusted, "Accessibility",
                          hotkey.trusted ? "Granted. ⌃⌥ Space works in every app." : "Needed for the ⌃⌥ Space hotkey.") {
                        if !hotkey.trusted {
                            Button("Open Settings") { hotkey.requestAccess() }.buttonStyle(SmallButtonStyle())
                        }
                    }

                    section("Meet settings (set these by hand)")
                    manual("Meet › Settings › Audio › Microphone", "BlackHole 2ch")
                    manual("Meet › Settings › Audio › Speakers", "BlackHole 16ch")
                    manual("macOS › Sound › Output", "your earphones")

                    section("Engine")
                    check(model.engineFound, model.engineFound ? "Engine found" : "Engine not found", EngineLocation.summary) {
                        HStack(spacing: 6) {
                            if model.engineBundled && model.engineUsesCheckout {
                                Button("Use Built-in") { model.useBundledEngine() }.buttonStyle(SmallButtonStyle())
                            }
                            Button(model.engineBundled && !model.engineUsesCheckout ? "Use a Checkout…"
                                   : (model.engineFound ? "Change…" : "Choose Folder…")) {
                                actions.hidePanel()
                                model.chooseEngineFolder()
                                actions.showPanel()
                            }
                            .buttonStyle(SmallButtonStyle())
                        }
                    }
                    if let msg = model.engineMessage { check(false, "That folder is not an engine", msg) }
                }
            }
            .scrollIndicators(.never)
        }
        .onAppear {
            model.refresh()
            UserDefaults.standard.set(true, forKey: "setupSeen")
        }
    }

    // MARK: Steps

    private var steps: [(String, Bool)] {
        [("Audio drivers", model.driversDone), ("Gemini key", model.keyDone),
         ("Permissions", model.permissionsDone(accessibility: hotkey.trusted))]
    }

    /// "Step 2 of 3 · Gemini key" with three pills, or "Ready" when everything passes.
    private var stepper: some View {
        let next = steps.firstIndex { !$0.1 }
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                ForEach(Array(steps.enumerated()), id: \.offset) { i, step in
                    HStack(spacing: 5) {
                        Image(systemName: step.1 ? "checkmark.circle.fill" : "\(i + 1).circle")
                            .foregroundStyle(step.1 ? Theme.ok : (i == next ? Theme.accent : Theme.text4))
                        Text(step.0)
                            .font(Theme.ui(12, i == next ? 600 : 500))
                            .foregroundStyle(i == next ? Theme.text : Theme.text3)
                    }
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .surfaceCard(radius: 99, border: i == next ? Theme.accentLine : Theme.line)
                }
                Spacer(minLength: 0)
            }
            Text(next.map { "Step \($0 + 1) of 3 · " + nextHint($0) } ?? "Ready. Press Done, then Start in the panel.")
                .font(Theme.ui(12))
                .foregroundStyle(Theme.text3)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func nextHint(_ i: Int) -> String {
        switch i {
        case 0: return "Install the two free BlackHole audio drivers."
        case 1: return "Paste your Gemini API key."
        default: return "Allow the microphone and Accessibility."
        }
    }

    // MARK: Cards

    private var installCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 10) {
                Text(DriverInstaller.bundledDir == nil
                     ? "Downloads Existential Audio's signed installers (about 200 KB) and asks for your Mac password once."
                     : "Installs both drivers from the copies inside kana and asks for your Mac password once.")
                    .font(Theme.ui(12))
                    .foregroundStyle(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Button(model.installing ? "Installing…" : "Install audio drivers") { model.installDrivers() }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(model.installing || !model.blackholeMissing)
            }
            switch model.install {
            case .idle: EmptyView()
            case .working(let msg): resultLine(true, msg)
            case .done(let msg): resultLine(true, msg)
            case .failed(let msg): resultLine(false, msg)
            case .needsRestart:
                resultLine(false, "Installed, but macOS has not loaded the drivers yet. Restart your Mac, then open kana again.")
            }
            Text("Audio stops for a second while macOS reloads its drivers. BlackHole is free software by Existential Audio (GPL-3.0, source: github.com/ExistentialAudio/BlackHole).")
                .font(Theme.ui(11))
                .foregroundStyle(Theme.text4)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Text("Or in Terminal: " + SetupModel.brewLine)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Theme.text4)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button(copied ? "Copied" : "Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(SetupModel.brewLine, forType: .string)
                    copied = true
                }
                .buttonStyle(SmallButtonStyle())
            }
        }
        .padding(12)
        .surfaceCard()
    }

    private var testCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Text("Plays a 1 s tone into each BlackHole and listens for it. Not during a call.")
                    .font(Theme.ui(12))
                    .foregroundStyle(Theme.text3)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Button(model.testing ? "Testing…" : "Test devices") { model.testDevices() }
                    .buttonStyle(SmallButtonStyle())
                    .disabled(model.testing || (model.bh2 == nil && model.bh16 == nil) || engine.running)
            }
            ForEach(Array(model.testResults.enumerated()), id: \.offset) { _, r in
                resultLine(r.ok, r.text)
            }
        }
        .padding(12)
        .surfaceCard()
    }

    private var keyCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                SecureField("Paste a key from AI Studio", text: $keyField)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .surfaceCard(radius: 10, border: Theme.lineInput)
                Button("Save") { model.saveKey(keyField); keyField = "" }
                    .buttonStyle(SmallButtonStyle())
                    .disabled(keyField.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            HStack(spacing: 8) {
                Button("Test key") { model.testKey(typed: keyField) }.buttonStyle(SmallButtonStyle())
                if model.keySource == .keychain {
                    Button("Remove from Keychain") { model.removeKey() }.buttonStyle(SmallButtonStyle())
                }
                Spacer()
            }
            if let msg = model.keyMessage { resultLine(model.keyMessageOK, msg) }
            Link("Get a free key at aistudio.google.com/apikey ↗", destination: URL(string: "https://aistudio.google.com/apikey")!)
                .font(Theme.ui(12, 500))
                .foregroundStyle(Theme.accent)
            Text("Stored in your login Keychain and passed to the engine in its environment, never on the command line."
                 + (model.engineUsesCheckout ? " A .env file still works when no Keychain key is set." : ""))
                .font(Theme.ui(12))
                .foregroundStyle(Theme.text4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .surfaceCard()
    }

    // MARK: Pieces

    private func section(_ title: String) -> some View {
        Text(title)
            .font(Theme.ui(12, 500))
            .foregroundStyle(Theme.text4)
            .padding(.top, 6)
    }

    private func check(_ ok: Bool, _ title: String, _ detail: String) -> some View {
        check(ok, title, detail) { EmptyView() }
    }

    @ViewBuilder
    private func check<A: View>(_ ok: Bool, _ title: String, _ detail: String, @ViewBuilder action: () -> A) -> some View {
        let row = HStack(alignment: .top, spacing: 10) {
            Image(systemName: ok ? "checkmark.circle" : "xmark.circle")
                .font(.system(size: 16))
                .foregroundStyle(ok ? Theme.ok : Theme.accent)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Theme.ui(13, 600))
                    .foregroundStyle(ok ? Theme.text : Theme.alertTitle)
                Text(detail)
                    .font(Theme.ui(12))
                    .foregroundStyle(ok ? Theme.text3 : Theme.alertText)
                    .lineLimit(3)
                    .truncationMode(.middle)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
            action()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        if ok { row.surfaceCard() } else { row.alertCard() }
    }

    private func resultLine(_ ok: Bool, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: ok ? "checkmark.circle" : "xmark.circle")
                .foregroundStyle(ok ? Theme.ok : Theme.accent)
            Text(text)
                .font(Theme.ui(12))
                .foregroundStyle(Theme.text2)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
    }

    private func manual(_ place: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "hand.point.right")
                .foregroundStyle(Theme.text4)
                .frame(width: 16)
            Text(place).foregroundStyle(Theme.text3)
            Spacer(minLength: 4)
            Text(value).font(Theme.ui(13, 600))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .surfaceCard()
    }

    private var micText: String {
        switch model.micStatus {
        case .authorized: return "Granted."
        case .denied, .restricted: return "Denied. Turn kana on in Privacy › Microphone."
        default: return "Not asked yet. The engine needs it to hear you."
        }
    }

    private var keySourceText: String {
        switch model.keySource {
        case .keychain: return "In use: Keychain."
        case .dotenv(let path): return "In use: \(path)."
        case .environment: return "In use: GEMINI_API_KEY from the environment."
        case .missing: return model.engineUsesCheckout
            ? "Paste a key below, or put GEMINI_API_KEY in the engine's .env."
            : "Paste a key below. It is free to create and starts with AIza."
        }
    }

    private func openPrivacy(_ anchor: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(anchor)") {
            NSWorkspace.shared.open(url)
        }
    }
}
