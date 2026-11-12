# Security

kana handles two sensitive things: your Gemini API key and the audio of your meetings. This page says where each one goes.

## Supported versions

Only the latest release and the `main` branch get fixes.

## Your API key

**In the app.** Paste the key on the Setup page and press **Save**. It is stored as a generic password in your login Keychain (service `com.selvaragulkumar.kana`, account `GEMINI_API_KEY`). When the app starts the engine, it passes the key in the engine's environment, never on the command line, so it does not show up in `ps`. **Remove from Keychain** on the same page deletes it.

**On the command line, or as a fallback.** The engine reads `GEMINI_API_KEY` from the environment. If it is not set, it loads a `.env` file from the current directory, then from the repository root (python-dotenv). The app also falls back to `.env` when no Keychain key is set, and Setup shows which source is in use. Create the file so only you can read it:

```sh
printf 'GEMINI_API_KEY=%s\n' 'your-key' > .env
chmod 600 .env
```

`.env` is listed in `.gitignore`, so `git add` skips it. kana does not check the file mode for you.

kana never writes the key anywhere else, never prints it, and never sends it to the app over the JSON protocol.

**Test key** on the Setup page only checks the key's format today. It does not call Google.

If a key leaks, delete it in [Google AI Studio](https://aistudio.google.com/apikey) and create a new one. A leaked key can run up charges on your Google account.

## What is sent where

| Data | Leaves your Mac? | Destination |
|---|---|---|
| Your microphone audio (16 kHz mono PCM) | Only while Talk is on, and by default only the parts the voice gate judges as speech. While muted the outbound session is sent nothing except one end-of-audio marker when you mute. | `generativelanguage.googleapis.com` (Gemini Live API, WebSocket over TLS) |
| Meeting audio captured from BlackHole 16ch | While the engine runs and the inbound session is connected, by default only the parts judged as speech | `generativelanguage.googleapis.com` |
| Your API key | Yes, as the request credential | `generativelanguage.googleapis.com` |
| Transcripts and translated audio | Received from Google, played and shown locally. Transcripts are also saved to disk by default (below). | none |
| Device names, settings | No | none |

That host is the only one the engine contacts. The Swift app makes no network connections at all. It starts the engine as a child process and talks to it over stdin and stdout. There is no telemetry, no analytics and no crash reporting.

The voice gate (`--vad auto`, the default) sends speech plus up to 300 ms before it and 2 s after it. With `--vad off` every chunk is sent while the session is up.

## What is written to disk

- **Transcripts, by default.** Each run writes `YYYY-MM-DD-HHMM.md` and `.srt` to `~/Library/Application Support/kana/transcripts/`. They hold both sides of the conversation in plain, unencrypted text. Turn this off with "Save transcripts" in the app or `--no-save` on the command line, or move it with `--save-dir`. Delete the folder to remove them.
- **Audio, only on request.** Translated audio is written only when you pass `--dump-in` or `--dump-out`.
- **Logs, never.** The app keeps the last 4 KB of engine error output in memory only.

How Google stores and uses the audio you send depends on your Gemini API tier and Google's terms. Read the [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) before you use kana in a meeting where that matters. Tell the other participants that the call is being sent to an interpreting service.

## macOS permissions

- **Microphone.** Needed to read your mic and the BlackHole 16ch device. macOS asks once for kana.app, or for your terminal app when you run the engine from a terminal.
- **Accessibility.** Only for the global ⌃⌥Space hotkey. The app uses it to receive key-down events and checks only for that one key combination. Without it, the talk bar in the panel still works.

The panel and the caption strip are hidden from screen sharing, recordings and screenshots by default; turn on "Visible in screen share" to show them.

The app is ad-hoc signed and not sandboxed. Build it from source if you want to read every line that runs.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

1. Use GitHub's private vulnerability reporting on this repository (Security tab, "Report a vulnerability").
2. If that is not available, contact the maintainer, Selva Ragul Kumar, through the contact section of [selvaragulkumar.com](https://selvaragulkumar.com/#contact).

Include what you found, how to reproduce it, and the version or commit. Remove your API key from any logs you attach. You will get a reply within 7 days. This is a one-person project, so there is no bug bounty.
