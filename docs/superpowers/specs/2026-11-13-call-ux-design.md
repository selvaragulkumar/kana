# Call UX after the first real Meet call (2026-11-13)

The owner's first real Meet call asked for four changes. Decisions were made before this spec;
it records how they are built and where they are tested.

## 1. Talk key: hold Right ⌥ to talk, tap to toggle

- **Choices** (`TalkKey` in `Prefs.swift`, UserDefaults key `talkKey`): Right ⌥ (default,
  keyCode 61), Right ⌘ (keyCode 54), Fn/Globe (keyCode 63, `.function` flag), ⌃⌥Space (keyCode
  49 on `.keyDown`, the old toggle). The three modifier keys are watched with global and local
  `.flagsChanged` monitors; pressed or released is read from the device-dependent flag bit
  (right ⌥ `0x40`, right ⌘ `0x10`) or `.function`, so the left-hand key never fires. The
  local monitor passes modifier events on; ⌃⌥Space is still swallowed locally as before.
- **Hold or tap** (`TalkKeyLogic`, pure, no AppKit): press while off turns talk on at once.
  Release within 350 ms keeps it on (a tap latches). Release after 350 ms turns it off (push to
  talk). Press while on turns it off at once (the second tap). Before each press the logic is
  synced to the engine's talk state, so a talk-bar click or engine restart never leaves it stale.
  ⌃⌥Space only toggles.
- **Hint** `Hotkey.hint` is an instance property (`⌥ right`, `⌘ right`, `fn`, `⌃⌥Space`) used by
  the talk bar pill, tooltips, the mini bar and Setup. Picker: ••• › Talk key (panel menu and the
  menu-bar right-click menu) and a row in Setup › Permissions. Fn notes that macOS must have
  Keyboard › "Press 🌐 key to" set to "Do Nothing", or it opens the emoji picker.
- Accessibility is still required for the global monitor.

## 2. Mini bar: the mark is Start/Stop and breathes while live

- The mark is a button: idle or passing through → Start with the panel's saved device and
  language prefs (`EngineProcess.startWithSavedPrefs()`, the same UserDefaults keys the panel's
  `@AppStorage` uses); live → Stop. Tooltip "Start"/"Stop", pointing-hand cursor. Expanding stays
  on the hover button and a double-click on the bar.
- Mark: talking → `.talking`; error → `.error`; connecting → `.connecting`; connected live → the
  still mark with one `phaseAnimator` breathe (scale 1.0 → 1.06, opacity 0.85 → 1, 0.9 s each
  way = 1.8 s period). Reduce Motion: opacity only. The still mark is used instead of
  `.listening` so the bar never shows two motions at different periods. Idle and pass-through: the
  idle mark, no breathing.

## 3. Pass-through when kana is open but not live

**Engine** `--passthrough`: no key, no network. Two `audio.Passthrough(src, dst)` copy loops:
BlackHole 16ch (`--meet-spk`) → your earphones (`--spk`), your microphone (`--mic`) → BlackHole
2ch (`--meet-mic`). Each opens an InputStream (1 channel = channel 0 of the device) and an
OutputStream (up to 2 channels, the mono copied to each) at the source's native rate when the
sink accepts it, else the sink's native rate with linear resampling; 10 ms blocks, latency `low`,
int16. A deque of blocks bridges the two callbacks; above 50 ms queued the oldest block is
dropped (clock drift), an underrun plays silence.

Loop safety (`audio.check_passthrough`, fatal `DeviceError` before any stream opens): the
earphones may not be a BlackHole device, and no sink may be a device another loop captures
(nothing ever writes to BlackHole 16ch). The outbound mic is **not** gated by talk: Meet hears the
microphone directly, as without kana; the user mutes in Meet. The panel says so in plain words.

Protocol: `ready` carries `"mode": "passthrough"` and `in`/`out` `{src, sink}` (no model fields);
a live `ready` has no `mode`. `{"cmd":"quit"}` or stdin EOF → `bye`. Device failures are fatal
`error` events with exit 2, as in live mode. No `talk`, `transcript`, `session`, `audio`, `usage`
or `saved`; any command other than quit is a non-fatal `error`.

**App** `EngineProcess` has one child at a time and a kind: live or pass-through. `running` still
means a live session (so the existing UI keeps its meaning); `passingThrough` is the new state.

```
            launch / pref on / Setup Done   (drivers + mic permission, pref on)
   idle ───────────────────────────────────────────▶ passing through
    ▲  ◀── pass-through error (card, no retry) ────────┘   │   ▲
    │                                                      │   │ live exit (Stop, or error)
    │  Start (pref off)        Start: quit, wait exit ─────┘   │
    └──────────────────────▶ live ◀────────────────────────────┘
```

- Start while passing through: send quit, and launch the live engine from the old process's
  exit (devices are released by then; `stop()` still terminates after 2 s).
- Live exit (Stop or a failure) → pass-through again when the pref is on and drivers + mic
  permission are present. A pass-through failure never restarts by itself; a live error card is
  not overwritten by a pass-through error.
- Changing the microphone or earphones while passing through restarts it with the new devices.
- Pref `passthroughWhenIdle` (default on), toggle "Pass audio through when idle" in both menus.
- UI: pill "Passing through"; talk bar is one grey line "Meet hears your mic directly · mute in
  Meet", disabled, and the talk key does nothing (`setTalk` needs a live session); menu-bar and
  mini bar use the idle mark. The transcript of the last session is kept.

## 4. The panel's × quits kana

`AppActions.quit()` is the one quit path (×, ••• › Quit kana, footer Quit, menu-bar Quit):
`NSApp.terminate`, whose `applicationWillTerminate` sends quit to whichever engine runs and waits
up to 1.5 s for it to exit. Tooltip "Quit kana". The panel reopens from the menu-bar icon.

## Test seams

- `tests/test_audio.py`: `Passthrough` with an injected fake `sounddevice` copies input blocks to
  the output callback (rates, channels, drift drop); `check_passthrough` refuses a BlackHole
  earphone and a sink that is a source.
- `tests/test_events.py`: the pass-through `ready` encodes; `run_passthrough` emits `ready` with
  `mode`, ignores `talk` with a non-fatal error and ends on quit and on EOF; `main --passthrough`
  needs no key.
- `app/fake_engine.py --passthrough`: `ready` with `mode`, then waits for quit, `bye`.
- `app/check_talk_key.sh`: compiles `TalkKeyLogic.swift` (Foundation only) alone with
  `app/checks/talk_key/main.swift` and runs its checks: tap, hold, the 350 ms edge, second tap,
  sync. Command Line Tools have no XCTest, and a swift-testing target needs runtime libraries
  only Xcode ships, so a test target in `Package.swift` was not used.
