import AppKit
import AVFoundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

/// `kana --render-intro <dir>`: renders the opening intro, the panel, the minimized bar and the
/// panel → bar transition to PNG frames (plus GIFs and contact sheets) without opening any
/// window. Views are drawn by an NSHostingView that is never put in a window.
@MainActor
enum IntroRender {
    static let scale: CGFloat = 2

    static func run(to dir: URL) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        EngineProcess.previewMode = true
        let prefs = Prefs.shared
        let actions = AppActions(prefs: prefs)
        let hotkey = Hotkey {}

        func panel(_ engine: EngineProcess, t: Double?) -> some View {
            PanelView()
                .environmentObject(engine)
                .environmentObject(hotkey)
                .environmentObject(prefs)
                .environmentObject(actions)
                .environment(\.kanaIntroTime, t)
        }

        // 1. Intro: idle panel, 0 → 0.95 s every 50 ms, at the window height of that instant.
        let idle = EngineProcess(prefs: prefs)
        idle.loadPreview(rows: [], running: false, live: false)
        var introFrames: [CGImage] = []
        var t = 0.0
        while t <= PanelView.introLength + 0.051 {
            let h = PanelView.introHeight(t)
            if let img = image(panel(idle, t: t), size: CGSize(width: PanelView.size.width, height: h)) {
                let framed = onCanvas(img, canvas: CGSize(width: 480, height: 760), at: CGPoint(x: 20, y: 20))
                introFrames.append(framed)
                write(framed, dir.appendingPathComponent(String(format: "intro-%04d.png", Int((t * 1000).rounded()))))
            }
            t += 0.05
        }
        writeGIF(introFrames, delay: 0.05, last: 1.2, to: dir.appendingPathComponent("intro.gif"))
        writeSheet(stride(from: 0, to: introFrames.count, by: 2).map { introFrames[$0] }, cols: 5,
                   to: dir.appendingPathComponent("intro-frames.png"))

        // 2. Panel stills: idle, live with a transcript, fake engine.
        let live = EngineProcess(prefs: prefs)
        live.loadPreview(rows: demoRows, running: true, live: true)
        let fake = EngineProcess(prefs: prefs)
        fake.loadPreview(rows: [], running: false, live: false,
                         inputs: [AudioDevice(index: 0, name: "Fake Mic 1"), AudioDevice(index: 1, name: "Fake Mic 2")],
                         outputs: [AudioDevice(index: 2, name: "Fake Speaker 1")], fake: true)
        let full = PanelView.size
        let panelLive = image(panel(live, t: nil), size: full)
        for (name, e) in [("panel-idle", idle), ("panel-fake", fake)] {
            if let img = image(panel(e, t: nil), size: full) { write(img, dir.appendingPathComponent("\(name).png")) }
        }
        if let panelLive { write(panelLive, dir.appendingPathComponent("panel-live.png")) }

        // 3. Minimized bar: idle, live with two lines, talking.
        let barSize = MiniBarController.size
        func bar(_ e: EngineProcess) -> some View {
            MiniBarView(onExpand: {}, onClose: {}).environmentObject(e).environmentObject(CaptionHover())
        }
        let talking = EngineProcess(prefs: prefs)
        talking.loadPreview(rows: demoRows, running: true, live: true, talking: true)
        var barLive: CGImage?
        for (name, e) in [("bar-idle", idle), ("bar-live", live), ("bar-talking", talking)] {
            if let img = image(bar(e), size: barSize) {
                write(onCanvas(img, canvas: CGSize(width: 420, height: 104), at: CGPoint(x: 20, y: 20)),
                      dir.appendingPathComponent("\(name).png"))
                if name == "bar-live" { barLive = img }
            }
        }
        // A new line arriving: before and after.
        let before = EngineProcess(prefs: prefs)
        before.loadPreview(rows: Array(demoRows.prefix(3)), running: true, live: true)
        if let a = image(bar(before), size: barSize), let b = barLive {
            writeSheet([a, b], cols: 1, to: dir.appendingPathComponent("bar-new-line.png"))
        }

        // 4. Panel → bar collapse, with the same geometry as PanelBarTransition: the panel
        // snapshot is cropped from the top inside a frame that eases to the bar's frame and
        // fades out over the bar background; radius 18 → 14; 350 ms, cubic-bezier(.6,0,.3,1).
        if let snap = panelLive, let barImg = barLive {
            var frames: [CGImage] = []
            let steps = 14
            for i in 0...steps {
                let p = CubicBezier.trace(Double(i) / Double(steps))
                frames.append(collapseFrame(panel: snap, bar: barImg, p: p, showBar: i == steps))
            }
            frames.append(contentsOf: frames.reversed())     // expand is the reverse
            writeGIF(frames, delay: 0.025, last: 0.8, to: dir.appendingPathComponent("minimize-transition.gif"))
            writeSheet(stride(from: 0, through: steps, by: 2).map { frames[$0] }, cols: 4,
                       to: dir.appendingPathComponent("minimize-frames.png"))
        }
        print("rendered to \(dir.path)")
    }

    static let demoRows: [TranscriptRow] = [
        TranscriptRow(dir: .inbound, src: "こんにちは、聞こえますか？", dst: "Hello, can you hear me?"),
        TranscriptRow(dir: .outbound, src: "Yes, loud and clear.", dst: "はい、よく聞こえます。"),
        TranscriptRow(dir: .inbound, src: "今日は新しいカタログの件で相談したいです。", dst: "I'd like to talk about the new catalogue today."),
        TranscriptRow(dir: .inbound, src: "まず価格表から始めましょう。", dst: "Let's start with the price list."),
    ]

    // MARK: Drawing

    /// Draws a SwiftUI view with an NSHostingView that is never put in a window.
    static func image<V: View>(_ view: V, size: CGSize) -> CGImage? {
        let host = NSHostingView(rootView: view.environment(\.colorScheme, .dark))
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: .darkAqua)
        host.layoutSubtreeIfNeeded()
        guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(size.width * scale),
                                         pixelsHigh: Int(size.height * scale), bitsPerSample: 8, samplesPerPixel: 4,
                                         hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
                                         bytesPerRow: 0, bitsPerPixel: 0) else { return nil }
        rep.size = size
        host.cacheDisplay(in: host.bounds, to: rep)
        return rep.cgImage
    }

    private static func context(_ size: CGSize) -> CGContext {
        let c = CGContext(data: nil, width: Int(size.width * scale), height: Int(size.height * scale), bitsPerComponent: 8,
                          bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        c.scaleBy(x: scale, y: scale)
        c.setFillColor(Theme.ns(0x070708).cgColor)
        c.fill(CGRect(origin: .zero, size: size))
        return c
    }

    /// Places an image (top-left at `at`, y down) on a page-coloured canvas.
    static func onCanvas(_ img: CGImage, canvas: CGSize, at: CGPoint) -> CGImage {
        let c = context(canvas)
        let w = CGFloat(img.width) / scale, h = CGFloat(img.height) / scale
        c.draw(img, in: CGRect(x: at.x, y: canvas.height - at.y - h, width: w, height: h))
        return c.makeImage()!
    }

    /// One collapse frame at progress p (0 = panel, 1 = bar).
    static func collapseFrame(panel: CGImage, bar: CGImage, p: Double, showBar: Bool) -> CGImage {
        let canvas = CGSize(width: 480, height: 760)
        let c = context(canvas)
        let from = CGRect(x: 20, y: 20, width: 440, height: 720)            // y down
        let to = CGRect(x: 20, y: 20, width: MiniBarController.size.width, height: MiniBarController.size.height)
        func lerp(_ a: CGFloat, _ b: CGFloat) -> CGFloat { a + (b - a) * CGFloat(p) }
        let r = CGRect(x: lerp(from.minX, to.minX), y: lerp(from.minY, to.minY),
                       width: lerp(from.width, to.width), height: lerp(from.height, to.height))
        let flipped = CGRect(x: r.minX, y: canvas.height - r.maxY, width: r.width, height: r.height)
        let radius = lerp(18, 14)
        let path = CGPath(roundedRect: flipped, cornerWidth: radius, cornerHeight: radius, transform: nil)
        c.saveGState()
        c.addPath(path); c.setFillColor(Theme.ns(0x0E0E10).cgColor); c.fillPath()
        c.addPath(path); c.clip()
        c.setAlpha(CGFloat(1 - p))
        let pw = CGFloat(panel.width) / scale, ph = CGFloat(panel.height) / scale
        c.draw(panel, in: CGRect(x: flipped.minX, y: flipped.maxY - ph, width: pw, height: ph))   // top-left crop
        c.restoreGState()
        c.addPath(path); c.setStrokeColor(Theme.ns(0x26262A).cgColor); c.setLineWidth(1); c.strokePath()
        if showBar {
            c.draw(bar, in: CGRect(x: to.minX, y: canvas.height - to.maxY, width: to.width, height: to.height))
        }
        return c.makeImage()!
    }

    // MARK: Output

    static func write(_ img: CGImage, _ url: URL) {
        try? NSBitmapImageRep(cgImage: img).representation(using: .png, properties: [:])?.write(to: url)
    }

    static func writeGIF(_ frames: [CGImage], delay: Double, last: Double, to url: URL) {
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.gif.identifier as CFString, frames.count, nil) else { return }
        CGImageDestinationSetProperties(dest, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 0]] as CFDictionary)
        for (i, f) in frames.enumerated() {
            let d = i == frames.count - 1 ? last : delay
            CGImageDestinationAddImage(dest, f, [kCGImagePropertyGIFDictionary:
                [kCGImagePropertyGIFDelayTime: d, kCGImagePropertyGIFUnclampedDelayTime: d]] as CFDictionary)
        }
        CGImageDestinationFinalize(dest)
    }

    static func writeSheet(_ frames: [CGImage], cols: Int, to url: URL) {
        guard let first = frames.first else { return }
        let w = CGFloat(first.width) / scale / 2, h = CGFloat(first.height) / scale / 2, gap: CGFloat = 12
        let rows = (frames.count + cols - 1) / cols
        let size = CGSize(width: CGFloat(cols) * w + CGFloat(cols + 1) * gap, height: CGFloat(rows) * h + CGFloat(rows + 1) * gap)
        let c = context(size)
        for (i, f) in frames.enumerated() {
            let col = CGFloat(i % cols), row = CGFloat(i / cols)
            c.draw(f, in: CGRect(x: gap + col * (w + gap), y: size.height - gap - h - row * (h + gap), width: w, height: h))
        }
        write(c.makeImage()!, url)
    }
}

/// `kana --render-setup <dir>`: the Setup page in its first-launch states, drawn offscreen like
/// IntroRender (no window). Device, key and permission states are stubbed; Accessibility shows
/// this process's real state.
@MainActor
enum SetupRender {
    static func run(to dir: URL) {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        EngineProcess.previewMode = true
        let prefs = Prefs.shared
        let actions = AppActions(prefs: prefs)
        let hotkey = Hotkey {}
        let engine = EngineProcess(prefs: prefs)
        engine.loadPreview(rows: [], running: false, live: false)
        let both = [CADevice(id: 1, name: "BlackHole 2ch", inputChannels: 2, outputChannels: 2),
                    CADevice(id: 2, name: "BlackHole 16ch", inputChannels: 16, outputChannels: 16)]
        let states: [(String, [CADevice], KeySource, AVAuthorizationStatus, SetupModel.InstallState)] = [
            ("setup-1-fresh", [], .missing, .notDetermined, .idle),
            ("setup-2-installing", [], .missing, .notDetermined, .working("Waiting for your password…")),
            ("setup-3-restart", [], .missing, .notDetermined, .needsRestart),
            ("setup-4-key", both, .missing, .notDetermined, .done("Installed. No restart needed.")),
            ("setup-5-ready", both, .keychain, .authorized, .idle),
        ]
        for (name, devices, key, mic, install) in states {
            let model = SetupModel()
            model.loadPreview(devices: devices, key: key, mic: mic, install: install)
            let view = SetupView(model: model) {}
                .environmentObject(hotkey)
                .environmentObject(engine)
                .environmentObject(actions)
                .padding(20)
                .frame(width: PanelView.size.width, height: PanelView.size.height, alignment: .top)
                .background(RoundedRectangle(cornerRadius: 18).fill(Theme.bg))
                .foregroundStyle(Theme.text)
                .font(Theme.ui(13))
            if let img = IntroRender.image(view, size: PanelView.size) {
                IntroRender.write(img, dir.appendingPathComponent("\(name).png"))
            }
        }
        print("rendered to \(dir.path)")
    }
}
