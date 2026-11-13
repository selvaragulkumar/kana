# Fresh-Mac test

The one check a release cannot do on the developer's own Mac: install kana on a Mac that has never had kana, BlackHole or a Homebrew Python, and see the first-launch Setup do everything on its own. Thirty minutes. You need a Mac with Apple silicon (macOS 14 or later), earphones, and a Gemini API key (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey); nobody else needs to see it).

Please do the steps in order and write down what you see at each **Record** line, even when it is "fine". A screenshot of anything surprising is worth more than a description.

## Before you start

- **Record:** macOS version (Apple menu › About This Mac) and chip.
- Open System Settings › Sound › Output. **Record:** whether anything called BlackHole is listed. If it is, this Mac is not fresh; tell Rahul before continuing.

## 1. Install

1. Download `kana-<version>.dmg` and `checksums.txt` (from the link Rahul sent, or the GitHub release).
2. In Terminal: `shasum -a 256 ~/Downloads/kana-*.dmg` and compare with the line in `checksums.txt`. **Record:** match or not.
3. Open the DMG, drag **kana** onto **Applications**, eject the DMG.
4. Open kana from Applications. macOS will block it the first time because this build is not notarised.
   - macOS 14: right-click kana › Open › Open.
   - macOS 15 and later: open it once, then System Settings › Privacy & Security, press **Open Anyway** next to kana, confirm.
   **Record:** the exact wording of the warning and how many clicks it took.
5. kana appears in the menu bar only (no Dock icon): look for the 「 」 mark at the top right. If you cannot find it, click the desktop so Finder is in front, or open kana again from Spotlight, which brings its panel up. **Record:** did the panel open, and did the opening animation play smoothly.

## 2. Setup: audio drivers (the main thing we are testing)

1. The panel opens with Setup. Press **Install audio drivers** and enter your Mac password once.
2. **Record:** how long it took, every prompt you saw, and the exact text of any error.
3. When it finishes, open System Settings › Sound › Output. **Record:** are **BlackHole 2ch** and **BlackHole 16ch** both listed, without logging out or restarting?
4. If Setup says a restart is needed, restart, reopen kana. **Record:** that the restart was needed.

## 3. Setup: key and permissions

1. Paste your Gemini key and press **Save**. **Record:** any error.
2. Allow the microphone when asked. Turn on kana under Accessibility when Setup sends you there. **Record:** did Setup move on by itself after each grant, or did you have to press something.
3. Quit kana (••• menu › Quit) and open it again from Spotlight. **Record:** does it still show Accessibility as granted, or ask again.

## 4. One call

1. Start a Google Meet with yourself (a second device or Rahul). In Meet's settings set Microphone = **BlackHole 2ch** and Speakers = **BlackHole 16ch**. Keep the Mac's own output on your earphones.
2. In kana, choose your microphone and earphones in the pickers, press **Start**, wait for the IN and OUT dots to turn green.
3. Press the **Press to talk** bar (or ⌃⌥Space) and say two short English sentences. **Record:** did the other side hear Japanese, roughly how many seconds behind, and did the panel show both the English and the Japanese lines.
4. Have the other side say something in Japanese (a YouTube clip in Japanese played into the call also works). **Record:** did you hear English in your earphones, and did the footer's delay readout show a number.
5. Press **Minimize**, then expand it again. **Record:** anything that flickered or got stuck.
6. Press **Stop**, then **Quit**.

## 5. Uninstall (so the Mac is fresh again, optional)

Follow the Uninstall section of the README. **Record:** anything it left behind.

## Send back

The notes from every **Record** line, the screenshots, and your macOS version. If something blocked you, stop there and send what you have; a half-finished list is still useful.
