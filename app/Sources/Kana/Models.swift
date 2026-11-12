import Foundation

/// An audio device as reported by `--list-devices --json`.
struct AudioDevice: Identifiable, Hashable, Decodable {
    let index: Int
    let name: String
    var id: String { "\(index):\(name)" }
}

struct DeviceList: Decodable {
    let inputs: [AudioDevice]
    let outputs: [AudioDevice]
    /// Set by app/fake_engine.py: the names are test data, not this Mac's devices.
    let fake: Bool?
}

/// One utterance: what was heard (source) and what the model said (translation).
struct TranscriptRow: Identifiable, Equatable {
    let id = UUID()
    let dir: Direction
    var src: String
    var dst: String
    /// Last time either side changed; the caption strip fades lines out from here.
    var updatedAt = Date()
}

enum Direction: String {
    case inbound = "in"
    case outbound = "out"

    var glyph: String { self == .inbound ? "arrow.down" : "arrow.up" }
    var label: String { self == .inbound ? "IN" : "OUT" }
}

/// One decoded engine event. Unknown fields are ignored; unknown events decode with `ev` only.
struct EngineEvent: Decodable {
    let ev: String
    let t: Double?
    // talk
    let on: Bool?
    // transcript / session / audio
    let dir: String?
    let kind: String?
    let text: String?
    let final: Bool?
    let state: String?
    let detail: String?
    let sent_s: Double?
    let recv_s: Double?
    let gated_s: Double?
    let usd: Double?          // audio tick / usage: engine-computed cost from server-reported tokens
    let latency_ms: Double?
    // latency (per utterance)
    let onset_to_audio_ms: Double?
    let src_final_to_dst_final_ms: Double?
    // saved
    let md: String?
    let srt: String?
    // error
    let fatal: Bool?
    // ready
    let model: String?
    let in_model: String?
    let out_model: String?
    let register: String?
    let in_lang: String?
    let out_lang: String?
}

/// Session state per direction, shown as a tiny label in the footer.
enum SessionState: String {
    case none = "–"
    case connecting = "connecting"
    case connected = "connected"
    case reconnecting = "reconnecting"
    case closed = "closed"

    /// Compact form for the footer.
    var short: String {
        switch self {
        case .none: return "–"
        case .connecting: return "…"
        case .connected: return "live"
        case .reconnecting: return "retry"
        case .closed: return "off"
        }
    }
}
