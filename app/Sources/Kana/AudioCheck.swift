import AVFoundation
import CoreAudio
import Foundation

/// A CoreAudio device with its channel counts. Read directly, without the engine, so Setup
/// works even when the Python side is not installed yet.
struct CADevice: Hashable {
    let id: AudioDeviceID
    let name: String
    let inputChannels: Int
    let outputChannels: Int
}

enum CoreAudioDevices {
    static func all() -> [CADevice] {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size) == noErr else { return [] }
        var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids) == noErr else { return [] }
        return ids.compactMap { id in
            guard let name = name(of: id) else { return nil }
            return CADevice(id: id, name: name,
                            inputChannels: channels(of: id, scope: kAudioObjectPropertyScopeInput),
                            outputChannels: channels(of: id, scope: kAudioObjectPropertyScopeOutput))
        }
    }

    /// Exact BlackHole name match first, then a case-insensitive substring (as the engine does).
    static func find(_ name: String, in devices: [CADevice]) -> CADevice? {
        devices.first { $0.name == name } ?? devices.first { $0.name.localizedCaseInsensitiveContains(name) }
    }

    private static func name(of id: AudioDeviceID) -> String? {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                                              mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var name: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &name) == noErr, let n = name else { return nil }
        return n.takeRetainedValue() as String
    }

    private static func channels(of id: AudioDeviceID, scope: AudioObjectPropertyScope) -> Int {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
                                              mScope: scope, mElement: kAudioObjectPropertyElementMain)
        var size: UInt32 = 0
        guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
        let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { raw.deallocate() }
        guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
        let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
        return list.reduce(0) { $0 + Int($1.mNumberChannels) }
    }
}

/// Plays a 1 s 440 Hz tone into a device's output and records the same device's input.
/// BlackHole loops its output back to its input, so a healthy device hears the tone.
enum LoopbackTester {
    struct Outcome {
        let ok: Bool
        let text: String
    }

    private final class Meter: @unchecked Sendable {
        private let lock = NSLock()
        private var peakRMS: Float = 0
        private var bestFreq: Double = 0

        func feed(_ buffer: AVAudioPCMBuffer) {
            guard let ch = buffer.floatChannelData?[0] else { return }
            let n = Int(buffer.frameLength)
            guard n > 1 else { return }
            var sum: Float = 0
            var crossings = 0
            for i in 0..<n {
                sum += ch[i] * ch[i]
                if i > 0 && (ch[i - 1] < 0) != (ch[i] < 0) { crossings += 1 }
            }
            let rms = (sum / Float(n)).squareRoot()
            let freq = Double(crossings) / 2 / (Double(n) / buffer.format.sampleRate)
            lock.lock()
            if rms > peakRMS { peakRMS = rms; bestFreq = freq }
            lock.unlock()
        }

        var result: (Float, Double) { lock.lock(); defer { lock.unlock() }; return (peakRMS, bestFreq) }
    }

    /// Runs off the main thread; takes about 1.5 s.
    static func run(device: CADevice) async -> Outcome {
        await withCheckedContinuation { cont in
            DispatchQueue.global(qos: .userInitiated).async {
                cont.resume(returning: runBlocking(device: device))
            }
        }
    }

    private static func setDevice(_ unit: AudioUnit?, _ id: AudioDeviceID) -> OSStatus {
        guard let unit else { return -1 }
        var dev = id
        return AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0,
                                    &dev, UInt32(MemoryLayout<AudioDeviceID>.size))
    }

    private static func runBlocking(device: CADevice) -> Outcome {
        guard device.inputChannels > 0, device.outputChannels > 0 else {
            return Outcome(ok: false, text: L10n.f("%@ has no input/output pair to loop back", device.name))
        }
        let engine = AVAudioEngine()
        // Input and output both on the BlackHole device; nothing else is touched.
        guard setDevice(engine.outputNode.audioUnit, device.id) == noErr,
              setDevice(engine.inputNode.audioUnit, device.id) == noErr else {
            return Outcome(ok: false, text: L10n.f("Could not select %@", device.name))
        }
        let outRate = engine.outputNode.outputFormat(forBus: 0).sampleRate
        let inFormat = engine.inputNode.outputFormat(forBus: 0)
        guard outRate > 0, inFormat.sampleRate > 0, inFormat.channelCount > 0 else {
            return Outcome(ok: false, text: L10n.f("%@ reports no audio format", device.name))
        }

        let player = AVAudioPlayerNode()
        engine.attach(player)
        guard let mono = AVAudioFormat(standardFormatWithSampleRate: outRate, channels: 1),
              let tone = AVAudioPCMBuffer(pcmFormat: mono, frameCapacity: AVAudioFrameCount(outRate)) else {
            return Outcome(ok: false, text: L10n.t("Could not build the test tone"))
        }
        tone.frameLength = tone.frameCapacity
        let samples = tone.floatChannelData![0]
        for i in 0..<Int(tone.frameLength) {
            samples[i] = 0.25 * Float(sin(2 * Double.pi * 440 * Double(i) / outRate))
        }
        engine.connect(player, to: engine.mainMixerNode, format: mono)

        let meter = Meter()
        engine.inputNode.installTap(onBus: 0, bufferSize: 4096, format: inFormat) { buf, _ in meter.feed(buf) }
        do {
            engine.prepare()
            try engine.start()
        } catch {
            engine.inputNode.removeTap(onBus: 0)
            return Outcome(ok: false, text: "\(device.name): \(error.localizedDescription)")
        }
        player.scheduleBuffer(tone, at: nil, options: [])
        player.play()
        Thread.sleep(forTimeInterval: 1.4)
        player.stop()
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()

        let (rms, freq) = meter.result
        let db = rms > 0 ? 20 * log10(Double(rms)) : -120
        let level = String(format: "%.0f dB, ≈%.0f Hz", db, freq)
        if rms > 0.01 && abs(freq - 440) < 40 {
            return Outcome(ok: true, text: L10n.f("%@ loopback OK (%@)", device.name, level))
        }
        if rms <= 0.0001 {
            return Outcome(ok: false, text: L10n.f("%@: silence came back. Check Microphone access for kana.", device.name))
        }
        return Outcome(ok: false, text: L10n.f("%@: unexpected signal (%@)", device.name, level))
    }
}

/// Microphone permission (TCC). The engine is our child process, so its capture counts as ours.
enum MicPermission {
    static var status: AVAuthorizationStatus { AVCaptureDevice.authorizationStatus(for: .audio) }

    static func request() async -> Bool {
        await AVCaptureDevice.requestAccess(for: .audio)
    }
}
