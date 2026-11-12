import AppKit
import SwiftUI

/// Language presets: the meeting language Meet hears, paired with English for you. All BCP-47.
enum LanguagePresets {
    static let english = "en"
    static let meeting = ["ja", "zh", "ko", "es", "fr", "de", "hi", "ta"]

    /// The language's own name (English, 日本語, 中文, 한국어 …).
    static func name(_ code: String) -> String {
        let base = code.split(separator: "-").first.map(String.init) ?? code
        let n = Locale(identifier: base).localizedString(forLanguageCode: base) ?? code
        return n.prefix(1).uppercased() + n.dropFirst()
    }

    static func isValid(_ tag: String) -> Bool {
        tag.range(of: #"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$"#, options: .regularExpression) != nil
    }
}

/// The interpreter panel from design/kana-design.html: 440 × 720, opaque dark.
struct PanelView: View {
    @EnvironmentObject private var engine: EngineProcess
    @EnvironmentObject private var hotkey: Hotkey
    @EnvironmentObject private var prefs: Prefs
    @EnvironmentObject private var actions: AppActions
    @StateObject private var setup = SetupModel()

    @AppStorage("mic") private var mic = ""
    @AppStorage("spk") private var spk = ""
    @AppStorage("inLang") private var inLang = "en"
    @AppStorage("outLang") private var outLang = "ja"
    @AppStorage("businessKeigo") private var businessKeigo = false

    @State private var showSetup = false
    @State private var setupDismissed = false
    @State private var customOpen = false
    @State private var customIn = ""
    @State private var customOut = ""

    static let size = CGSize(width: 440, height: 720)

    // Opening intro (from idle). The window opens compact (440 × 220) with the mark centred
    // and tracing itself; then the window grows to full height, anchored at the top, while the
    // mark flies into its header slot and the content fades up. The window frame is animated
    // by StatusController on the same clock; the content here is laid out at full height and
    // clipped by the window, so nothing reflows while it grows.
    static let compactHeight: CGFloat = 220
    static let growStart: Double = 1.10      // design trace 0–0.99 s, short hold, then grow
    static let growDuration: Double = 0.35   // grow + move + fade-up 0.75–1.10 s
    static var introLength: Double { growStart + growDuration }

    @State private var introRunning = false
    @State private var introT0 = Date.distantPast
    @State private var headerMarkFrame = CGRect(x: 20, y: 26, width: 24, height: 24)
    @Environment(\.kanaIntroTime) private var fixedIntroTime
    private let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

    struct IntroFrame {
        var markOpacity = 1.0            // the mark fades in first
        var trace1 = 1.0, trace2 = 1.0   // how much of each bracket is drawn (design k-trace)
        var move = 1.0                   // 0 → 1 while the window grows and the mark flies
        var content = 1.0                // opacity of everything but the header mark
        var markInHeader = true
        var active = false
    }

    /// The intro at time t (s), from the design handoff's trace motion (k-trace, 1.8 s,
    /// cubic-bezier(.6,0,.3,1)): the white bracket draws itself over 0–35 % (0–0.63 s), the red
    /// one over 20–55 % (0.36–0.99 s); a short hold, then the mark flies into the header while
    /// the window grows.
    static func introFrame(_ t: Double, reduceMotion: Bool) -> IntroFrame {
        if reduceMotion { return IntroFrame(content: min(max(t / 0.15, 0), 1), active: true) }
        func c(_ x: Double) -> Double { min(max(x, 0), 1) }
        let e = CubicBezier.trace
        let move = CubicBezier.trace(c((t - growStart) / growDuration))
        return IntroFrame(trace1: e(c(t / 0.63)), trace2: e(c((t - 0.36) / 0.63)),
                          move: move, content: move, markInHeader: t >= introLength, active: true)
    }

    /// Window height during the intro (also used to render frames offscreen).
    static func introHeight(_ t: Double) -> CGFloat {
        let p = CubicBezier.trace(min(max((t - growStart) / growDuration, 0), 1))
        return compactHeight + (size.height - compactHeight) * p
    }

    private func startIntro(_ d: Date) {
        introT0 = d
        introRunning = true
        DispatchQueue.main.asyncAfter(deadline: d.addingTimeInterval(reduceMotion ? 0.2 : Self.introLength + 0.05).dispatchTime) {
            if introT0 == d { introRunning = false }
        }
    }

    var body: some View {
        let animating = introRunning && fixedIntroTime == nil
        TimelineView(.animation(paused: !animating)) { ctx in
            let t = fixedIntroTime ?? ctx.date.timeIntervalSince(introT0)
            let f = (introRunning || fixedIntroTime != nil)
                ? Self.introFrame(t, reduceMotion: reduceMotion && fixedIntroTime == nil) : IntroFrame()
            Group {
                if showSetup {
                    SetupView(model: setup) { showSetup = false; setupDismissed = true }
                        .opacity(f.content)
                } else {
                    main(f)
                }
            }
            .padding(20)
            .frame(width: Self.size.width, height: Self.size.height, alignment: .top)
            .overlay(alignment: .topLeading) {
                if f.active && !(reduceMotion && fixedIntroTime == nil) { introMark(f) }
            }
            // The window (not this view) decides the visible height; keep everything top-aligned.
            .frame(width: Self.size.width, height: fixedIntroTime.map { Self.introHeight($0) }, alignment: .top)
            .frame(maxHeight: .infinity, alignment: .top)
            .background(RoundedRectangle(cornerRadius: 18).fill(Theme.bg))
            .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Theme.line))
            .clipShape(RoundedRectangle(cornerRadius: 18))
        }
        .coordinateSpace(name: "kanaPanel")
        .onPreferenceChange(HeaderMarkKey.self) { headerMarkFrame = $0 }
        .foregroundStyle(Theme.text)
        .font(Theme.ui(13))
        .environment(\.colorScheme, .dark)
        .onAppear {
            panelOpened()
            if let d = actions.introStart, Date().timeIntervalSince(d) < 0.5 { startIntro(d) }
        }
        .onChange(of: actions.introStart) { _, d in if let d { startIntro(d) } else { introRunning = false } }
        .onReceive(NotificationCenter.default.publisher(for: .kanaPanelDidOpen)) { _ in panelOpened() }
        .onChange(of: engine.needsSetup) { _, need in if need { showSetup = true } }
        .onChange(of: actions.setupRequested) { _, req in
            if req { showSetup = true; actions.setupRequested = false }
        }
    }

    /// The mark: 96 pt centred in the compact window, rolling, then easing into the header slot.
    private func introMark(_ f: IntroFrame) -> some View {
        let start = CGPoint(x: Self.size.width / 2, y: Self.compactHeight / 2)
        let end = CGPoint(x: headerMarkFrame.midX, y: headerMarkFrame.midY)
        let size = 96 + (24 - 96) * f.move
        let center = CGPoint(x: start.x + (end.x - start.x) * f.move, y: start.y + (end.y - start.y) * f.move)
        var frame = MarkGeometry.Frame()
        frame.trim1 = 0...f.trace1
        frame.trim2 = 0...f.trace2
        let stroke = 20 + (26 - 20) * f.move
        return Canvas { gc, _ in
            var g = gc
            MarkGeometry.draw(in: &g, size: size, frame: frame, color1: .white, color2: Theme.accent, strokeWidth: stroke)
        }
        .frame(width: size, height: size)
        .position(center)
        .allowsHitTesting(false)
        .opacity(f.markInHeader ? 0 : f.markOpacity)
    }

    private func main(_ f: IntroFrame) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            header(f)
            Group {
                if engine.isFakeEngine { fakeBanner }
                talkBar
                if !hotkey.trusted { accessibilityNotice }
                if let err = engine.lastError { errorCard(err) }
                if !engine.running { deviceFields }
                languageCard
                if engine.rows.isEmpty && !engine.running {
                    emptyState
                } else {
                    transcript
                }
                footer
            }
            .opacity(f.content)
            .offset(y: 8 * (1 - f.content))
        }
    }

    private func panelOpened() {
        engine.refreshDevices()
        hotkey.recheck()
        setup.refresh()
        // The main panel never nags about BlackHole; Setup lists it. Setup opens by itself
        // when a start fails with a device or key error (engine.needsSetup), and on the first
        // open of a launch while something a new user must do is still missing (drivers, key,
        // microphone, engine). Done dismisses it until the next launch.
        if !setupDismissed && !engine.running && EngineLocation.overrideCommand == nil && !EngineProcess.previewMode
            && setup.needsFirstRun(accessibility: hotkey.trusted) {
            showSetup = true
        }
    }

    // MARK: Header

    private func header(_ f: IntroFrame) -> some View {
        HStack(spacing: 8) {
            HStack(spacing: 10) {
                KanaMark(state: engine.markState, size: 24)
                    .opacity(f.markInHeader ? 1 : 0)
                    .background(GeometryReader { g in
                        Color.clear.preference(key: HeaderMarkKey.self, value: g.frame(in: .named("kanaPanel")))
                    })
                Text(Theme.name)
                    .font(Theme.brand(20))
                    .tracking(-0.4)
                    .fixedSize()
                    .opacity(f.move)
                StatePill(live: engine.running)
                    .fixedSize()
                    .padding(.leading, 6)
                    .help(engine.model == nil ? "" : engine.engineTooltip)
                    .opacity(f.content)
            }
            Spacer(minLength: 4)
            Group {
                overflowMenu
                Button {
                    actions.minimize()
                } label: {
                    Image(systemName: "minus").font(.system(size: 13, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
                .help("Minimize")
                Button {
                    actions.hidePanel()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
                .help("Close")
                if engine.running {
                    Button("Stop") { engine.stop() }
                        .buttonStyle(GhostButtonStyle(square: true))
                        .keyboardShortcut(.cancelAction)
                } else {
                    Button("Start") {
                        engine.start(mic: mic, spk: spk, inLang: inLang, outLang: outLang, business: businessKeigo)
                    }
                    .buttonStyle(PrimaryButtonStyle())
                    .keyboardShortcut(.defaultAction)
                }
            }
            .opacity(f.content)
        }
    }

    private var overflowMenu: some View {
        Menu {
            Toggle("Captions", isOn: $prefs.captionsOn)
            Toggle("Visible in screen share", isOn: $prefs.visibleInShare)
            Toggle("Save transcripts", isOn: $prefs.saveTranscripts)
            Divider()
            Button("Open Last Transcript") { actions.openLastTranscript() }
                .disabled(actions.lastTranscriptURL == nil)
            Button("Transcripts Folder") { actions.openTranscriptsFolder() }
            Divider()
            Button("Setup…") { showSetup = true }
            Divider()
            Button("Quit kana") { NSApplication.shared.terminate(nil) }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.text3)
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .frame(minWidth: 28, minHeight: 28)
        .help("More")
    }

    // MARK: Talk bar

    private var talkBar: some View {
        let on = engine.talking
        let enabled = engine.running && engine.ready
        return Button {
            engine.toggleTalk()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "mic")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(on ? Theme.accent : Theme.text4)
                if on {
                    Text("Talking · \(LanguagePresets.name(inLang)) → \(LanguagePresets.name(outLang))")
                        .font(Theme.ui(15, 600))
                        .foregroundStyle(.white)
                } else {
                    Text("Press to talk")
                        .font(Theme.ui(15, 500))
                        .foregroundStyle(Theme.text4)
                }
                Spacer()
                if on {
                    LevelMeter()
                } else {
                    Text("⌃⌥ Space")
                        .font(Theme.ui(12))
                        .foregroundStyle(Theme.text3)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 3)
                        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.c(0x2E2E33)))
                }
            }
            .padding(.horizontal, 16)
            .frame(maxWidth: .infinity, minHeight: 52, maxHeight: 52)
            .background(RoundedRectangle(cornerRadius: 14).fill(on ? Theme.accentBg : Theme.surface))
            .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(on ? Theme.accent : Theme.line))
            .contentShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .help(enabled ? "Toggle talking (⌃⌥ Space)" : "Start a session first")
    }

    // MARK: Warning cards

    /// Shown whenever the fake test engine is in use, so test data is never mistaken for real.
    private var fakeBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Theme.accent)
            Text("FAKE ENGINE — test data, not your devices")
                .font(Theme.ui(12, 600))
                .foregroundStyle(Theme.alertTitle)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .alertCard()
    }

    private var accessibilityNotice: some View {
        HStack(spacing: 10) {
            Image(systemName: "keyboard")
                .foregroundStyle(Theme.text2)
            Text("Hotkey needs Accessibility access.")
                .foregroundStyle(Theme.text2)
            Spacer()
            Button("Open Settings") { hotkey.requestAccess() }
                .buttonStyle(SmallButtonStyle())
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .surfaceCard()
    }

    @ViewBuilder
    private func errorCard(_ text: String) -> some View {
        if engine.lastErrorFatal {
            alertRow(title: "Engine stopped", detail: text) {
                Button {
                    engine.dismissError()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle(color: Theme.alertText))
                .help("Dismiss")
            }
        } else {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundStyle(Theme.text3)
                Text(text)
                    .foregroundStyle(Theme.text2)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Spacer(minLength: 0)
                Button {
                    engine.dismissError()
                } label: {
                    Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(IconButtonStyle())
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .surfaceCard()
        }
    }

    private func alertRow<A: View>(title: String, detail: String, @ViewBuilder action: () -> A) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "xmark.circle")
                .font(.system(size: 16))
                .foregroundStyle(Theme.accent)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Theme.ui(13, 600))
                    .foregroundStyle(Theme.alertTitle)
                Text(detail)
                    .font(Theme.ui(12))
                    .foregroundStyle(Theme.alertText)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
            action()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .alertCard()
    }

    // MARK: Devices

    private var deviceFields: some View {
        VStack(spacing: 8) {
            field("Microphone", selection: $mic, devices: engine.inputs)
            field("Earphones", selection: $spk, devices: engine.outputs)
        }
    }

    private func field(_ label: String, selection: Binding<String>, devices: [AudioDevice]) -> some View {
        let names = Array(Set(devices.map(\.name).filter { !$0.localizedCaseInsensitiveContains("BlackHole") })).sorted()
        return HStack(spacing: 10) {
            Text(label)
                .foregroundStyle(Theme.text3)
                .frame(width: 96, alignment: .leading)
            Menu {
                Button("System default") { selection.wrappedValue = "" }
                if !names.isEmpty { Divider() }
                ForEach(names, id: \.self) { n in
                    Button(engine.devicesAreFake ? "\(n) (fake)" : n) { selection.wrappedValue = n }
                }
            } label: {
                HStack {
                    Text(selectionLabel(selection.wrappedValue, names))
                        .foregroundStyle(engine.devicesAreFake ? Theme.text4 : Theme.text)
                        // Inter ships no italic, so fake names use the system italic.
                        .font(engine.devicesAreFake ? .system(size: 13).italic() : Theme.ui(13))
                        .lineLimit(1)
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Theme.text3)
                }
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, minHeight: 34)
                .surfaceCard(radius: 10, border: Theme.lineInput)
                .contentShape(Rectangle())
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
        }
    }

    private func selectionLabel(_ value: String, _ names: [String]) -> String {
        if value.isEmpty { return "System default" }
        return names.contains(value) ? value : "\(value) (not found)"
    }

    // MARK: Languages

    private var languageCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                presetsMenu { side("You hear", LanguagePresets.name(inLang), trailing: false) }
                Button {
                    swap(&inLang, &outLang)
                } label: {
                    Image(systemName: "arrow.left.arrow.right")
                        .font(.system(size: 14, weight: .medium))
                        .frame(width: 40, height: 40)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surface2))
                        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.lineStrong))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(engine.running)
                .help("Swap languages")
                presetsMenu {
                    side(engine.register == "business" ? "Meet hears · business keigo" : "Meet hears",
                         LanguagePresets.name(outLang), trailing: true)
                }
            }
            if customOpen { customLanguages }
            if outLang.lowercased().hasPrefix("ja") { registerRow }
            if let err = engine.devicesError {
                Text(err).font(Theme.ui(12)).foregroundStyle(Theme.alertText)
            }
        }
    }

    private func side(_ label: String, _ value: String, trailing: Bool) -> some View {
        VStack(alignment: trailing ? .trailing : .leading, spacing: 2) {
            Text(label)
                .font(Theme.ui(11))
                .foregroundStyle(Theme.text4)
                .lineLimit(1)
            Text(value)
                .font(Theme.text(value, size: 13, weight: 500))
                .foregroundStyle(Theme.text)
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, minHeight: 50, maxHeight: 50, alignment: trailing ? .trailing : .leading)
        .surfaceCard(radius: 10)
        .contentShape(Rectangle())
    }

    private func presetsMenu<L: View>(@ViewBuilder label: () -> L) -> some View {
        Menu {
            ForEach(LanguagePresets.meeting, id: \.self) { code in
                Button {
                    inLang = LanguagePresets.english
                    outLang = code
                    customOpen = false
                } label: {
                    let current = inLang == LanguagePresets.english && outLang == code
                    Text("\(LanguagePresets.name(code)) ⇄ English  (\(code)/en)\(current ? "  ✓" : "")")
                }
            }
            Divider()
            Button("Custom…") {
                customIn = inLang
                customOut = outLang
                customOpen = true
            }
        } label: {
            label()
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        .disabled(engine.running)
        .help("Language pair")
    }

    private var customLanguages: some View {
        HStack(spacing: 8) {
            TextField("You hear", text: $customIn)
                .textFieldStyle(.plain)
                .padding(.horizontal, 10).padding(.vertical, 7)
                .surfaceCard(radius: 10, border: Theme.lineInput)
            TextField("Meet hears", text: $customOut)
                .textFieldStyle(.plain)
                .padding(.horizontal, 10).padding(.vertical, 7)
                .surfaceCard(radius: 10, border: Theme.lineInput)
            Button("Apply") {
                inLang = customIn.trimmingCharacters(in: .whitespaces)
                outLang = customOut.trimmingCharacters(in: .whitespaces)
                customOpen = false
            }
            .buttonStyle(SmallButtonStyle())
            .disabled(!LanguagePresets.isValid(customIn.trimmingCharacters(in: .whitespaces))
                      || !LanguagePresets.isValid(customOut.trimmingCharacters(in: .whitespaces)))
            Button {
                customOpen = false
            } label: {
                Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
            }
            .buttonStyle(IconButtonStyle())
        }
    }

    /// Compact, right-aligned: "Business keigo" and a mini switch; the stock-voice note is the tooltip.
    private var registerRow: some View {
        HStack(spacing: 6) {
            Spacer()
            Text("Business keigo")
                .font(Theme.ui(11))
                .foregroundStyle(Theme.text3)
            Toggle("Business keigo", isOn: $businessKeigo)
                .labelsHidden()
                .toggleStyle(.switch)
                .controlSize(.mini)
                .tint(Theme.accent)
                .disabled(engine.running)
        }
        .help("Business keigo: polite Japanese guaranteed, but the outbound voice is a stock voice, not yours.")
    }

    // MARK: Transcript

    private var emptyState: some View {
        VStack(spacing: 10) {
            Spacer(minLength: 0)
            Canvas { gc, size in
                var g = gc
                MarkGeometry.draw(in: &g, size: size.width, frame: .init(), color1: Theme.text4, color2: Theme.text4)
            }
            .frame(width: 40, height: 40)
            .opacity(0.5)
            Text("Press Start to begin interpreting")
                .foregroundStyle(Theme.text3)
            Text("Transcripts appear here, original beside translation.")
                .font(Theme.ui(12))
                .foregroundStyle(Theme.text4)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .overlay(alignment: .top) { Rectangle().fill(Theme.lineSoft).frame(height: 1) }
    }

    private var transcript: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Transcript")
                Spacer()
                HStack(spacing: 14) {
                    Text("↓ from Meet")
                    Text("↑ from you")
                }
            }
            .font(Theme.ui(12))
            .foregroundStyle(Theme.text4)
            .padding(.top, 12)
            .overlay(alignment: .top) { Rectangle().fill(Theme.lineSoft).frame(height: 1) }

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        if engine.rows.isEmpty {
                            Text("Listening…")
                                .foregroundStyle(Theme.text4)
                                .frame(maxWidth: .infinity, minHeight: 120)
                        }
                        ForEach(engine.rows) { row in
                            TranscriptRowView(row: row).id(row.id)
                        }
                    }
                }
                .scrollIndicators(.never)
                .onChange(of: engine.rows.last?.id) { _, id in
                    guard let id else { return }
                    withAnimation(.easeOut(duration: 0.15)) { proxy.scrollTo(id, anchor: .bottom) }
                }
                .onChange(of: engine.rows.last?.dst) { _, _ in
                    if let id = engine.rows.last?.id { proxy.scrollTo(id, anchor: .bottom) }
                }
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    // MARK: Footer

    private var footer: some View {
        HStack(spacing: 10) {
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                Text(costLine(now: ctx.date))
                    .monospacedDigit()
                    .foregroundStyle(engine.running ? Theme.text : Theme.text3)
                    .lineLimit(1)
                    .fixedSize()
            }
            .help(silenceTooltip)
            Spacer(minLength: 4)
            HStack(spacing: 14) {
                stream("IN", engine.inState, engine.latencyMs["in"])
                stream("OUT", engine.outState, engine.latencyMs["out"])
                Button("Quit") { NSApplication.shared.terminate(nil) }
                    .buttonStyle(.plain)
                    .font(Theme.ui(13, 500))
                    .foregroundStyle(Theme.text)
                    .keyboardShortcut("q")
            }
        }
        .font(Theme.ui(12))
        .foregroundStyle(Theme.text3)
        .padding(.top, 12)
        .overlay(alignment: .top) { Rectangle().fill(Theme.lineSoft).frame(height: 1) }
    }

    private func costLine(now: Date) -> String {
        let secs = engine.startedAt.map { max(0, Int(now.timeIntervalSince($0))) } ?? 0
        let time = String(format: "%d:%02d", secs / 60, secs % 60)
        let usd = String(format: "$%.2f", engine.usd)
        let jpy = "≈¥\(Int((engine.usd * EngineProcess.jpyPerUSD).rounded()))"
        let est = engine.running && engine.costIsEstimate ? " est." : ""
        return "\(time) · \(usd) · \(jpy)\(est)"
    }

    private var silenceTooltip: String {
        let i = engine.gatedS["in"] ?? 0, o = engine.gatedS["out"] ?? 0
        let saved = (i + o) * 0.0000875
        var s = String(format: "Silence skipped (not sent): IN %.0f s · OUT %.0f s, about $%.3f saved", i, o, saved)
        if engine.costIsEstimate { s += "\nEstimate from audio seconds until the engine reports token usage." }
        if engine.model != nil {
            s += "\n\n" + (engine.engineChip.map { "Engine: \($0)\n" } ?? "") + engine.engineTooltip
        }
        return s
    }

    private func stream(_ name: String, _ state: SessionState, _ latency: Double?) -> some View {
        let live = state == .connected
        let word: String
        switch state {
        case .connected: word = "live"
        case .connecting: word = "…"
        case .reconnecting: word = "retry"
        case .closed: word = "closed"
        case .none: word = engine.running ? "–" : "closed"
        }
        let lat = latency.map { String(format: " · %.1f s", $0 / 1000) } ?? ""
        return HStack(spacing: 6) {
            Circle().fill(live ? Theme.ok : Theme.streamOff).frame(width: 6, height: 6)
            Text("\(name) \(word)\(live ? lat : "")")
                .monospacedDigit()
                .lineLimit(1)
        }
        .help(latencyTooltip(name.lowercased()))
    }

    private func latencyTooltip(_ dir: String) -> String {
        var lines = ["\(dir.uppercased()) session. The number is the median delay from speech onset to translated audio."]
        if let (o2a, s2d) = engine.lastUtterance[dir] {
            let f = { (v: Double?) in v.map { String(format: "%.1f s", $0 / 1000) } ?? "–" }
            lines.append("Last utterance: onset→audio \(f(o2a)), text→translation \(f(s2d))")
        }
        return lines.joined(separator: "\n")
    }
}

/// One utterance: arrow, original (grey), translation (strong). Japanese uses Noto Sans JP.
struct TranscriptRowView: View {
    let row: TranscriptRow

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(row.dir == .inbound ? "↓" : "↑")
                .font(Theme.ui(13))
                .foregroundStyle(row.dir == .inbound ? Theme.text4 : Theme.accent)
                .frame(width: 14, alignment: .leading)
                .help(row.dir == .inbound ? "From Meet" : "From you")
            Text(row.src.isEmpty ? "…" : row.src)
                .font(Theme.text(row.src, size: 13))
                .foregroundStyle(Theme.text3)
                .lineSpacing(3)
                .frame(maxWidth: .infinity, alignment: .leading)
            Group {
                if row.dst.isEmpty {
                    TypingDots().frame(maxWidth: .infinity, alignment: .leading)
                } else {
                    Text(row.dst)
                        .font(Theme.text(row.dst, size: 14))
                        .foregroundStyle(Theme.textStrong)
                        .lineSpacing(2)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .textSelection(.enabled)
        .fixedSize(horizontal: false, vertical: true)
    }
}

/// Where the header mark sits, so the intro mark can land on it.
struct HeaderMarkKey: PreferenceKey {
    static let defaultValue = CGRect(x: 20, y: 26, width: 24, height: 24)
    static func reduce(value: inout CGRect, nextValue: () -> CGRect) { value = nextValue() }
}

private extension Date {
    var dispatchTime: DispatchTime { .now() + max(0, timeIntervalSinceNow) }
}

/// Fixed intro time for offscreen rendering (`kana --render-intro`); nil = live clock.
private struct KanaIntroTimeKey: EnvironmentKey { static let defaultValue: Double? = nil }
extension EnvironmentValues {
    var kanaIntroTime: Double? {
        get { self[KanaIntroTimeKey.self] }
        set { self[KanaIntroTimeKey.self] = newValue }
    }
}
