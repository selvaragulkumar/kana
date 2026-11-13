// Checks for TalkKeyLogic (hold to talk, tap to toggle). Run with app/check_talk_key.sh.
// docs/superpowers/specs/2026-11-13-call-ux-design.md
import Foundation

var failures = 0
func check(_ ok: Bool, _ what: String, line: Int = #line) {
    if !ok { failures += 1; print("FAIL line \(line): \(what)") }
}

do {  // press turns talk on at once; a tap latches it
    var l = TalkKeyLogic()
    check(l.press(at: 10) == true, "press while off turns talk on")
    check(l.release(at: 10.2) == true, "release within 350 ms keeps talk on (tap)")
    check(l.talking, "tap leaves talking")
}
do {  // hold is push-to-talk
    var l = TalkKeyLogic()
    _ = l.press(at: 10)
    check(l.release(at: 10.36) == false, "release after 350 ms turns talk off (hold)")
}
do {  // the window edge counts as a tap
    var l = TalkKeyLogic()
    _ = l.press(at: 10)
    check(l.release(at: 10 + TalkKeyLogic.tapWindow) == true, "release at exactly 350 ms is a tap")
}
do {  // second tap: off on press, and stays off
    var l = TalkKeyLogic()
    _ = l.press(at: 10)
    _ = l.release(at: 10.1)
    check(l.press(at: 12) == false, "press while latched turns talk off")
    check(l.release(at: 12.1) == false, "its release keeps talk off")
    check(l.release(at: 15) == false, "a stray release keeps talk off")
}
do {  // a long press while latched also ends off
    var l = TalkKeyLogic()
    _ = l.press(at: 10)
    _ = l.release(at: 10.1)
    _ = l.press(at: 20)
    check(l.release(at: 25) == false, "hold while latched ends off")
}
do {  // sync adopts outside changes (talk bar, engine stop)
    var l = TalkKeyLogic()
    _ = l.press(at: 10)
    _ = l.release(at: 10.1)
    l.sync(false)
    check(l.press(at: 11) == true, "after an outside stop the next press turns talk on")
    check(l.release(at: 13) == false, "and a hold still ends it")
}
do {  // talk bar turned talk on: the key's press is the second tap
    var l = TalkKeyLogic()
    l.sync(true)
    check(l.press(at: 1) == false, "press after an outside start turns talk off")
    check(l.release(at: 5) == false, "and its release keeps it off")
}

if failures > 0 {
    print("TalkKeyLogic: \(failures) check(s) failed")
    exit(1)
}
print("TalkKeyLogic: all checks passed")
