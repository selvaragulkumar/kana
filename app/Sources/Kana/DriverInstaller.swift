import CryptoKit
import Foundation

/// Installs the BlackHole 2ch and 16ch drivers with one administrator prompt.
///
/// The installers are Existential Audio's own signed, notarised .pkg files. kana does not ship
/// them by default: the official binaries are "all rights reserved" (only BlackHole's source is
/// GPL-3.0), so the app downloads them, on the user's click, from the same URLs the Homebrew
/// casks use, and checks each against the cask's SHA-256 and the vendor's signing identity. A
/// build made with Existential Audio's permission can carry them in Contents/Resources/drivers
/// instead (release.sh with KANA_BUNDLE_DRIVERS=1); then nothing is downloaded.
///
/// The admin step copies the files into a root-owned temp folder, checks the SHA-256 again
/// there (so a file swapped after our check is never installed), runs `installer` for each,
/// then restarts coreaudiod so the new devices appear without a log-out.
enum DriverInstaller {
    struct Driver {
        let name: String          // CoreAudio device name
        let file: String          // pkg file name
        let url: URL
        let sha256: String
    }

    static let version = "0.7.1"
    /// From the Homebrew casks blackhole-2ch and blackhole-16ch (formulae.brew.sh/api/cask/<name>.json).
    static let drivers: [Driver] = [
        Driver(name: "BlackHole 2ch", file: "BlackHole2ch-\(version).pkg",
               url: URL(string: "https://existential.audio/downloads/BlackHole2ch-\(version).pkg")!,
               sha256: "57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf"),
        Driver(name: "BlackHole 16ch", file: "BlackHole16ch-\(version).pkg",
               url: URL(string: "https://existential.audio/downloads/BlackHole16ch-\(version).pkg")!,
               sha256: "57254e2f76cd40db7f3f715238b1a2cb2bd08819d38abf4087f2944f71a3641a"),
    ]
    static let signer = "Developer ID Installer: Existential Audio Inc. (Q5C99V536K)"
    static let sourceURL = "https://github.com/ExistentialAudio/BlackHole/tree/v\(version)"

    enum Failure: LocalizedError {
        case download(String, String)
        case checksum(String)
        case signature(String)
        case cancelled
        case script(String)

        var errorDescription: String? {
            switch self {
            case .download(let f, let why): return "Could not download \(f): \(why)"
            case .checksum(let f): return "\(f) did not match its published checksum, so it was not installed."
            case .signature(let f): return "\(f) is not signed by Existential Audio, so it was not installed."
            case .cancelled: return "Cancelled. Nothing was installed."
            case .script(let msg): return "The installer stopped: \(msg)"
            }
        }
    }

    /// Bundled pkgs, if this build carries them.
    static var bundledDir: URL? {
        guard let dir = Bundle.main.resourceURL?.appendingPathComponent("drivers", isDirectory: true),
              drivers.allSatisfy({ FileManager.default.fileExists(atPath: dir.appendingPathComponent($0.file).path) })
        else { return nil }
        return dir
    }

    /// Where downloads go: ~/Library/Caches/kana/drivers.
    static var cacheDir: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Caches")
        return base.appendingPathComponent("\(AppID.supportFolder)/drivers", isDirectory: true)
    }

    // MARK: Fetch and verify

    /// Returns verified local pkg files for the given drivers: bundled ones, or downloads.
    static func fetch(_ wanted: [Driver]) async throws -> [(Driver, URL)] {
        var out: [(Driver, URL)] = []
        for d in wanted {
            let local: URL
            if let dir = bundledDir {
                local = dir.appendingPathComponent(d.file)
            } else {
                local = cacheDir.appendingPathComponent(d.file)
                if !FileManager.default.fileExists(atPath: local.path) || (try? sha256(of: local)) != d.sha256 {
                    try await download(d, to: local)
                }
            }
            guard (try? sha256(of: local)) == d.sha256 else {
                try? FileManager.default.removeItem(at: local)
                throw Failure.checksum(d.file)
            }
            guard signedByVendor(local) else { throw Failure.signature(d.file) }
            out.append((d, local))
        }
        return out
    }

    private static func download(_ d: Driver, to dest: URL) async throws {
        try FileManager.default.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
        let tmp: URL, response: URLResponse
        do {
            (tmp, response) = try await URLSession.shared.download(from: d.url)
        } catch {
            throw Failure.download(d.file, error.localizedDescription)
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw Failure.download(d.file, "HTTP \(http.statusCode)")
        }
        try? FileManager.default.removeItem(at: dest)
        try FileManager.default.moveItem(at: tmp, to: dest)
    }

    static func sha256(of url: URL) throws -> String {
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// `pkgutil --check-signature`: trusted, and the leaf certificate is Existential Audio's.
    static func signedByVendor(_ pkg: URL) -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/sbin/pkgutil")
        p.arguments = ["--check-signature", pkg.path]
        let out = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return false }
        let text = String(decoding: out.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        p.waitUntilExit()
        return p.terminationStatus == 0
            && text.contains("signed by a developer certificate issued by Apple")
            && text.contains("1. \(signer)")
    }

    // MARK: The admin step

    /// The shell command run as root. Every path is single-quoted.
    static func shellCommand(for pkgs: [(Driver, URL)]) -> String {
        var lines = ["set -e", "D=$(/usr/bin/mktemp -d /tmp/kana-drivers.XXXXXX)", "trap '/bin/rm -rf \"$D\"' EXIT"]
        for (d, url) in pkgs {
            lines.append("/bin/cp \(q(url.path)) \"$D\"/\(q(d.file))")
            lines.append("echo \(q("\(d.sha256)  \(d.file)")) | (cd \"$D\" && /usr/bin/shasum -a 256 -c -s)")
        }
        for (d, _) in pkgs {
            lines.append("/usr/sbin/installer -pkg \"$D\"/\(q(d.file)) -target /")
        }
        // coreaudiod is restarted by launchd at once; this loads the new drivers without a log-out.
        lines.append("/usr/bin/killall coreaudiod || true")
        return lines.joined(separator: "\n")
    }

    /// The AppleScript that asks for the password once and runs `shellCommand` as root.
    static func appleScript(for pkgs: [(Driver, URL)]) -> String {
        let names = pkgs.map(\.0.name).joined(separator: " and ")
        let prompt = "kana wants to install the \(names) audio drivers."
        return "do shell script \(asString(shellCommand(for: pkgs))) with prompt \(asString(prompt)) with administrator privileges"
    }

    /// Runs the AppleScript with osascript (off the main thread); throws .cancelled when the
    /// user dismisses the password prompt.
    static func runAdmin(_ pkgs: [(Driver, URL)]) async throws {
        let script = appleScript(for: pkgs)
        let result: (Int32, String) = await withCheckedContinuation { cont in
            DispatchQueue.global(qos: .userInitiated).async {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                p.arguments = ["-e", script]
                let err = Pipe()
                p.standardError = err
                p.standardOutput = FileHandle.nullDevice
                do { try p.run() } catch {
                    cont.resume(returning: (-1, error.localizedDescription)); return
                }
                let text = String(decoding: err.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                p.waitUntilExit()
                cont.resume(returning: (p.terminationStatus, text))
            }
        }
        guard result.0 != 0 else { return }
        if result.1.contains("-128") || result.1.localizedCaseInsensitiveContains("cancel") { throw Failure.cancelled }
        let last = result.1.split(whereSeparator: \.isNewline).last.map(String.init) ?? "exit \(result.0)"
        throw Failure.script(last)
    }

    /// Waits up to `timeout` seconds for the named CoreAudio devices to appear.
    static func waitForDevices(_ names: [String], timeout: TimeInterval = 20) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let all = CoreAudioDevices.all()
            if names.allSatisfy({ CoreAudioDevices.find($0, in: all) != nil }) { return true }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    // MARK: Dry run

    /// `kana --driver-install-dry-run`: fetches and verifies the pkgs exactly as the button
    /// does (downloads unless bundled), prints the AppleScript and the root shell command, and
    /// installs nothing. No window is opened.
    static func dryRun() async -> Int32 {
        let all = CoreAudioDevices.all()
        let missing = drivers.filter { CoreAudioDevices.find($0.name, in: all) == nil }
        print("installed now: " + drivers.map { "\($0.name)=\(CoreAudioDevices.find($0.name, in: all) != nil ? "yes" : "no")" }
            .joined(separator: ", "))
        print("source: " + (bundledDir.map { "bundled \($0.path)" } ?? "download to \(cacheDir.path)"))
        let wanted = missing.isEmpty ? drivers : missing
        if missing.isEmpty { print("both drivers are present; showing the command for a reinstall of both") }
        do {
            let pkgs = try await fetch(wanted)
            for (d, url) in pkgs { print("verified \(d.file): sha256 \(d.sha256), signer \(signer), \(url.path)") }
            print("\n--- AppleScript (osascript -e) ---\n" + appleScript(for: pkgs))
            print("\n--- shell command run as root ---\n" + shellCommand(for: pkgs))
            return 0
        } catch {
            print("error: \(error.localizedDescription)")
            return 1
        }
    }

    // MARK: Quoting

    /// POSIX single quotes.
    static func q(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }

    /// An AppleScript string literal.
    static func asString(_ s: String) -> String {
        "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }
}
