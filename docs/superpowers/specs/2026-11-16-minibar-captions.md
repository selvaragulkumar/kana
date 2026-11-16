# Mini bar carries the captions (2026-11-16)

From the second real call (Zoom, 2026-11-16). Rahul saw the panel and the separate caption strip
on screen at once and asked for three changes:

1. While the panel is open, no separate caption overlay.
2. When minimised, the mini bar is the caption surface: the caption lines at caption size, the
   previous line smaller and dimmer above the current one.
3. The mic in the mini bar is clickable and toggles talk.

No engine or protocol change: talk already goes through `EngineProcess.toggleTalk()`.

## What is removed

- The caption strip: `CaptionStrip.swift` (`CaptionController`, `CaptionView`, `DragHandle`) and
  its creation in `KanaApp`. There is no caption window of its own any more.
- The **Captions** toggle in ••• and in the menu-bar right-click menu, and `Prefs.captionsOn`.
  With the strip gone it would switch nothing; the mini bar always shows the captions. The old
  UserDefaults keys `captionsOn` and `captionOrigin` are left unread.
- The L10n entries only the strip and the toggle used ("Captions", "Captions appear here…"),
  and the bar's old mic tooltips ("Talking", "Not talking (%@)").
- `docs/images/captions.png`.

## The bar

One window, `MiniBarController`, same style as before: borderless non-activating `NSPanel`,
floating, on all Spaces, `#0E0E10` background, 1 pt `#26262A` border, radius 14, shadow,
hidden from screen capture (`WindowPrivacy`), dragged by its background, double-click expands.

**Size 640 × 108 pt** (was 380 × 64). Why: the old strip's text box was 560 pt wide at 17 pt; the
bar adds the mark column (32 pt) on the left and the controls column (≈ 90 pt) on the right
around a caption column of ≈ 470 pt, so a current line at 20 pt fits about 45 Latin characters
or 23 Japanese characters per line, two lines, plus the previous line. 108 pt is the height of
those three lines in Japanese (the taller case: ≈ 20 + 3 + 2 × 29 pt) plus 12 pt padding top and
bottom; at 100 pt the Japanese two-line case lost a line (checked in the renders). Fixed size in
every state, so the saved position and the panel ↔ bar transition never change shape mid-call.

Layout, left to right:

- **Mark** (32 pt), vertically centred: Start / Stop as before, breathing while live, talking
  mark while talking. Pointing-hand cursor, tooltip Start / Stop.
- **Caption column**, bottom-aligned: previous inbound translation at 14 pt, `text4`, one line
  (head-truncated); current inbound translation at 20 pt weight 500, `textStrong`, at most two
  lines showing the end of the text: a longer turn scrolls up and its oldest lines are clipped
  at the top, instead of an ellipsis in mid-sentence. A new line slides up. With no caption
  yet, vertically centred: "Listening…" while live, "Not translating · mute in Meet" while
  passing through, "Idle. Click the mark to start." otherwise (14 pt, `text4`). Not
  hit-testable, so dragging works over the text.
- **Controls**, right, vertically centred: the IN / OUT dots (tooltip with delay and cost),
  swapped for expand and close while the pointer is over the bar (same width, so the captions
  never reflow), then the mic button, always visible.

## The mic button

A 28 pt circle button. States, in the panel talk bar's colours:

| State | Glyph | Look | Click | Tooltip |
|---|---|---|---|---|
| Not live (idle, pass-through, connecting) | `mic` | `text4`, 45 % | disabled | "Start a session first" |
| Live, not talking | `mic` | `text4` on `surface`, `line` border | talk on | talk key help (as the panel) |
| Talking | `mic.fill` | `accent` on `accentBg`, `accent` border | talk off | talk key help |

The click calls `engine.toggleTalk()`, exactly what the panel's talk bar does, so the talk key
logic (`TalkKeyLogic`, synced to the engine's talk state before each press) is untouched.

## Position

The saved origin (`miniOrigin`) is reused; a frame that no longer fits is clamped onto the
nearest screen's visible area instead of being dropped (the bar grew, so an old spot near an
edge would otherwise push it off screen). The default spot is still the panel's top-left
corner, clamped the same way.

## Renders

`kana --render-minibar <dir>` (offscreen, like `--render-setup`; `--lang ja` for Japanese) writes
`minibar-idle.png`, `minibar-live.png`, `minibar-talking.png`, and for checking `minibar-hover.png`
and `minibar-long.png`. Japanese renders use Japanese
captions (English heard, Japanese shown). Copies in `docs/images/` as `minibar-*.png` and
`minibar-*-ja.png`.
