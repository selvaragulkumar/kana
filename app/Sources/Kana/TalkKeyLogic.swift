import Foundation

// Foundation only, so `app/check_talk_key.sh` can compile it alone with its checks
// (Command Line Tools ship no XCTest, and swift-testing needs Xcode's runtime).

/// The hold-or-tap decision, free of AppKit so it can be tested with plain timestamps.
/// Press while off: talk on at once. Release within `tapWindow`: it was a tap, talk stays on.
/// Release later: push-to-talk, talk off. Press while on: talk off at once (the second tap).
struct TalkKeyLogic {
    static let tapWindow: TimeInterval = 0.35

    private(set) var talking = false
    private var pressedAt: TimeInterval?

    /// Adopts the real talk state (talk bar click, engine restart) before a press.
    mutating func sync(_ on: Bool) {
        if on != talking { talking = on; pressedAt = nil }
    }

    /// Key down. Returns the talk state to apply.
    mutating func press(at t: TimeInterval) -> Bool {
        if talking {
            talking = false
            pressedAt = nil
        } else {
            talking = true
            pressedAt = t
        }
        return talking
    }

    /// Key up. Returns the talk state to apply.
    mutating func release(at t: TimeInterval) -> Bool {
        if let p = pressedAt {
            pressedAt = nil
            if t - p > Self.tapWindow { talking = false }
        }
        return talking
    }
}
