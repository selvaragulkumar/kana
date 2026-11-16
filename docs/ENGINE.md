# kana engine

The engine is the Python package `kana`. It runs one live translation session per direction
(Gemini Live Translate by default, or OpenAI's `gpt-realtime-translate` with `--provider openai`)
and moves audio between your devices and the model. It runs on its own in a terminal,
and the menu-bar app drives it through a JSON-lines protocol on stdin and stdout.

```
python -m kana [flags]             # or the console script: kana [flags]
```

The API key comes from `GEMINI_API_KEY`, or `OPENAI_API_KEY` with `--provider openai`. The engine
reads it from the environment, from `.env` in the current directory, from `.env` in the repository
root, or from the file named by `--env-file`. A missing key is one fatal error naming the variable.
With `--backend vertex` no Gemini key is needed: the sessions run on Vertex AI with Google Cloud
application-default credentials (`gcloud auth application-default login`).

## Directions

| Direction | Hears | Plays to | Translates |
|---|---|---|---|
| `in` | the meeting (`--meet-spk`, default BlackHole 16ch) | your earphones (`--spk`) | `--out` language → `--in` language |
| `out` | your microphone (`--mic`) | the meeting (`--meet-mic`, default BlackHole 2ch) | `--in` language → `--out` language |

The outbound direction starts muted. It only sends audio while push-to-talk is on. The engine
refuses to start when both directions would capture the same device or play to the same device,
because that would create a feedback loop.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--mic NAME` | system default input | Your real microphone. Matched as a case-insensitive substring. |
| `--spk NAME` | system default output | Your earphones. Matched as a substring. |
| `--meet-mic NAME` | `BlackHole 2ch` (Windows: `CABLE-A`) | The device the meeting app uses as its microphone. A VB-Audio cable may be named by either end ("CABLE-A Output" finds "CABLE-A Input"). |
| `--meet-spk NAME` | `BlackHole 16ch` (Windows: `CABLE-B`) | The device the meeting app uses as its speakers. |
| `--in LANG` | `en` | The language you hear (BCP-47). |
| `--out LANG` | `ja` | The language the meeting hears (BCP-47). |
| `--provider gemini\|openai` | `gemini` | The translation engine. `openai` uses `gpt-realtime-translate` (see [OpenAI provider](#openai-provider)). |
| `--model ID` | `gemini-3.5-live-translate-preview` | The model. On Gemini, models without "translate" in the name get a translator system instruction instead. A `gpt-` model implies `--provider openai`; `--provider openai` alone picks `gpt-realtime-translate`. A model of the other provider is a fatal error. |
| `--env-file PATH` | none | Also reads API keys from this `.env` file. |
| `--register default\|business` | `default` | The outbound Japanese register (Gemini only; with `--provider openai`, `business` is a fatal error). `default` keeps Live Translate, with your own voice and your own register: casual English becomes casual Japanese. `business` (opt-in) sends the outbound direction to `gemini-3.8-live` with a keigo instruction, which guarantees です・ます and keigo but uses a stock voice. Inbound always uses `--model`. See [REGISTER.md](REGISTER.md). |
| `--in-file WAV` | none | A 16-bit WAV that replaces the meeting capture. Used for tests and dry runs. It starts playing once its session has connected. |
| `--out-file WAV` | none | A 16-bit WAV that replaces your microphone. Push-to-talk then starts on. |
| `--dump-in WAV` | none | Also writes the inbound translated audio (24 kHz mono) to this file. |
| `--dump-out WAV` | none | Also writes the outbound translated audio to this file. |
| `--only in\|out` | both | Runs a single direction. |
| `--list-devices` | | Lists audio devices and exits. With `--json` it prints one JSON line, with only the `--host-api` devices when one is set. |
| `--host-api NAME` | `auto` | Only devices of this PortAudio host API are used (a substring, such as `wasapi` or `mme`); a missing `--mic`/`--spk` then means that host API's default device. `auto` is WASAPI on Windows, where every device is listed once per host API and PortAudio's default (MME) is slow, and no filter elsewhere. `all` is no filter. Windows support is groundwork, see [research/windows.md](research/windows.md). |
| `--vad auto\|off` | `auto` | Voice-activity gating of what is sent. With `off`, every chunk is streamed. |
| `--vad-threshold RMS` | `200` | The absolute speech level: the int16 RMS of a 100 ms chunk. |
| `--vad-hangover MS` | `2000` | How long audio is still sent after speech ends, before the stream end. |
| `--catch-up on\|off` | `on` | While playback is behind, drops the silence the model streams, so its next words are not queued behind it. See [LATENCY.md](LATENCY.md). |
| `--backend developer\|vertex` | `developer` | Where the Live sessions run. `developer` is the Gemini Developer API (`generativelanguage.googleapis.com`) with `GEMINI_API_KEY`. `vertex` is Vertex AI at location `global` (the only location serving Live Translate) with application-default credentials; the Live config is the same. `ready` then reports `in_model` / `out_model` with an `@vertex` suffix. Measured side by side in [LATENCY.md](LATENCY.md). |
| `--gcp-project ID` | `GOOGLE_CLOUD_PROJECT`, then `gcloud config get-value project` | The Google Cloud project for `--backend vertex`. Without one the engine exits with a fatal error. |
| `--capture-latency low\|default` | `low` | With `low`, a BlackHole capture device (the meeting audio) is opened at PortAudio latency `low` with 10 ms blocks, collected into the 100 ms chunks the session gets. Each chunk then reaches the engine about 7 ms after its last sample instead of about 67 ms. Other inputs (your microphone) keep the defaults: they were not measured. `default` opens every input as before. See [LATENCY.md](LATENCY.md). |
| `--save-dir DIR` | `~/Library/Application Support/kana` (Windows: `%LOCALAPPDATA%\kana`) | Transcripts are written to `DIR/transcripts/`. |
| `--no-save` | | Saves no transcripts. |
| `--passthrough` | | No translation, no network, no key. Copies the meeting (`--meet-spk`) to your earphones (`--spk`) and your microphone (`--mic`) to the meeting (`--meet-mic`), untranslated. See [Pass-through](#pass-through). |
| `--voice-own-language off\|on` | `off` | Inbound speech that is already the language you hear (English spoken in the room reaching the remote microphone and coming back on the meeting audio). `off`: still transcribed and paired, marked `echo` in its `transcript` events, but its audio is not played. `on`: played like the rest (still marked). See [Own language coming back](#own-language-coming-back). |
| `--json` | | Runs the JSON-lines protocol described below. |

Exit codes: `0` is a clean exit and `2` is a fatal error, such as a missing key, a missing
device or a device that fails to open at start-up, or a device that stopped mid-call and stayed
gone for about 60 s (see Audio device dropouts).

## Pass-through

`--passthrough` makes the meeting behave as if kana were not there, while keeping the meeting
app's devices on BlackHole. The menu-bar app runs it whenever it is open but not live (pref "Pass
audio through when idle", on by default), so Meet is never silent between sessions.

| Loop | From | To |
|---|---|---|
| inbound | the meeting (`--meet-spk`, BlackHole 16ch) | your earphones (`--spk`) |
| outbound | your microphone (`--mic`) | the meeting (`--meet-mic`, BlackHole 2ch) |

- **The microphone is live to the meeting.** Pass-through does not gate the microphone by talk:
  the meeting hears it directly, exactly as without kana, and you mute in the meeting app. This is
  the one mode where kana sends your microphone with talk off, so the app says it in plain words
  ("Meet hears your mic directly · mute in Meet") and the talk key does nothing.
- **Native quality.** Each loop opens its input with one channel (channel 0 of the device) at the
  device's native rate, and its output at the same rate when the device accepts it, otherwise at
  the output's native rate with linear resampling. No 16 kHz step. Blocks are 10 ms at PortAudio
  latency `low`, int16; the mono signal is written to up to two output channels. Above 50 ms
  queued the oldest block is dropped (clock drift between the two devices); an underrun plays
  silence.
- **Loop-proof by construction.** It writes only to your earphones and to BlackHole 2ch, never to
  BlackHole 16ch. It refuses to start (fatal error, exit 2) when the earphones are a BlackHole
  device (for example when the system output was left on BlackHole) or when a BlackHole sink is
  also a captured source.
- No key is read and no connection is opened. `--in`, `--out`, `--model`, `--provider`, `--vad`
  and the file and dump flags do not apply. No transcripts are saved.

## Terminal mode

Without `--json`, the engine prints a banner, the path of the saved transcript and one line per
sentence. Lines look like `[IN ja->en] こんにちは。` and `[IN ja->en] => Hello.`. Space toggles
push-to-talk and `q` quits; this needs a terminal on stdin.

## JSON protocol (`--json`)

Stdout carries JSON lines only, one object per line, flushed at once. Every event has `"t"`
(unix seconds, float) and `"ev"`. The engine writes nothing to stderr except the text of a fatal
error. Strings are UTF-8, not `\u` escapes.

### Commands (stdin)

| Line | Effect |
|---|---|
| `{"cmd":"talk","on":true}` | Unmutes the outbound direction. A `talk` event acknowledges it. |
| `{"cmd":"talk","on":false}` | Mutes the outbound direction. |
| `{"cmd":"quit"}` | Shuts down cleanly with `bye`. End of input on stdin does the same. |

Any other line produces a non-fatal `error` event and is otherwise ignored. In `--passthrough`
only `quit` applies; `talk` gets a non-fatal `error`.

### Events (stdout), in the order they first appear

**`ready`**: the devices are open. A direction that is not running is `null`, and so is its model.
A file source is shown as `file <path>`. `model` is the `--model` flag, or the provider's default model when it is not given (`gpt-realtime-translate` names the OpenAI provider; no separate provider field). `in_model` and `out_model`
are the models each direction actually uses (with an `@vertex` suffix under `--backend vertex`),
and `register` is the `--register` flag.
```json
{"t": 1794481886.512, "ev": "ready", "in": {"src": "BlackHole 16ch", "sink": "MacBook Pro Speakers"}, "out": {"src": "MacBook Pro Microphone", "sink": "BlackHole 2ch"}, "model": "gemini-3.5-live-translate-preview", "register": "default", "in_model": "gemini-3.5-live-translate-preview", "out_model": "gemini-3.5-live-translate-preview", "in_lang": "en", "out_lang": "ja"}
```

With `--passthrough`, `ready` has `"mode": "passthrough"` and only the two loops; a live `ready`
has no `mode`. Pass-through sends no `saved`, `talk`, `session`, `transcript`, `latency`, `audio`
or `usage`: after `ready` come only `error` and `bye`.
```json
{"t": 1794481886.512, "ev": "ready", "mode": "passthrough", "in": {"src": "BlackHole 16ch", "sink": "AirPods Pro"}, "out": {"src": "AirPods Pro", "sink": "BlackHole 2ch"}}
```

**`saved`**: sent right after `ready`, unless `--no-save` is set. It names the two transcript files.
```json
{"t": 1794481109.185, "ev": "saved", "md": "~/Library/Application Support/kana/transcripts/2026-11-12-2001.md", "srt": "~/Library/Application Support/kana/transcripts/2026-11-12-2001.srt"}
```
The real event carries absolute paths; the `~` here only shortens the example.

**`talk`**: the outbound mute state. It is sent once at start and after every talk command.
```json
{"t": 1794481109.185, "ev": "talk", "on": false}
```

**`session`**: the connection state of a direction. `state` is `connected`, `reconnecting` or
`closed`. `detail` is `go_away` (a planned server handover), `error: ...` (a network or server
error, retried with backoff of 1, 2 and 4 s) or `""`. A reconnect resumes the session with the
latest resumption handle.
```json
{"t": 1794481109.628, "ev": "session", "dir": "in", "state": "connected", "detail": ""}
{"t": 1794481300.000, "ev": "session", "dir": "in", "state": "reconnecting", "detail": "go_away"}
```

**`transcript`**: text added to a transcript row, as it streams. `kind` is `src` for what was
heard and `dst` for what the model spoke. `text` is one transcription chunk as the model sent it
(about a second of speech), or the part of a chunk that went to this row; `row` is the
transcript row it belongs to (numbered from 1 per direction) and `row_text` is that whole side of
the row after it was added, so the app sets it and never pairs or joins. `final` is always
`true`: the text is never revised, only appended to. (Before pairing v2, 2026-11-16, an event
carried one finished sentence; the fields are the same.)
```json
{"t": 1794481308.975, "ev": "transcript", "dir": "in", "kind": "src", "text": "今日は", "row": 1, "row_text": "今日は", "final": true}
{"t": 1794481309.262, "ev": "transcript", "dir": "in", "kind": "dst", "text": "Today", "row": 1, "row_text": "Today", "final": true}
{"t": 1794481309.981, "ev": "transcript", "dir": "in", "kind": "src", "text": "いい天気ですね。", "row": 1, "row_text": "今日はいい天気ですね。", "final": true}
{"t": 1794481310.270, "ev": "transcript", "dir": "in", "kind": "dst", "text": " the weather is nice.", "row": 1, "row_text": "Today the weather is nice.", "final": true}
```
A row whose source is already the language you hear (see
[Own language coming back](#own-language-coming-back)) carries `"echo": true` on its
`transcript` events from the moment that was decided; if the same utterance then turns out to
be the meeting's language, its later events carry `"echo": false`. Rows that were never in
question have no `echo` field. The field is additive: an app that does not know it shows the row
as usual.
```json
{"t": 1794481320.114, "ev": "transcript", "dir": "in", "kind": "src", "text": "Can you share the screen?", "row": 7, "row_text": "Can you share the screen?", "final": true, "echo": true}
```
A `src` event with `merge_into` moves text that was shown as its own row: row `row` is removed
and `row_text` is the new source side of row `merge_into`. Pairing v2 never sends it; the v1
pairer did, when the model translated a short tag such as "Right?" together with the sentence
before it, and the app still applies it:
```json
{"t": 1794481312.004, "ev": "transcript", "dir": "out", "kind": "src", "text": "Right?", "row": 4, "merge_into": 3, "row_text": "I think it's sort of slow. Right?", "final": true}
```

### Pairing

The engine pairs what was heard with what the model said (`kana/pairing.py`, pairing v2; spec in
`docs/superpowers/specs/2026-11-16-pairing-v2.md`). Live Translate streams the input
transcription about one chunk a second while someone speaks, and the translation of each chunk
follows about 0.3 s later; it sends no turn signals (`docs/research/transcription-timing.md`).
So every chunk goes to the pairer the moment it arrives, and a translation chunk belongs with
the source chunk just before it. A row is cut where the English ends a sentence.

A translation chunk:

1. continues the last row while that row's translation has not ended a sentence (often a row a
   source chunk opened a moment before);
2. also continues it after a sentence end when the latest source chunk went into that row after
   the end, less than 2 s ago, or the row's source stops mid-clause (up to 160 CJK characters of
   source): the model is still translating that source, in a second sentence. A source put
   beside the wrong translation thus pulls its own translation after it: a row can grow, the
   rows after it do not shift;
3. otherwise opens a new row.

A source chunk:

1. is split over the rows at the end that have a translation and no source, in order and by
   length, when there are two or more (a late source; translated less than 30 s ago);
2. fills the last row when it has a translation and no source (an early translation);
3. continues the last row while its translation has not ended a sentence, except after 3 s of
   silence on both sides (new row), and except a source-only row that got no translation for
   5 s and is at a clause end, which is left untranslated (new row);
4. opens a new row when the last row's translation is done and its source ends at a clause end
   (`、。？！`);
5. otherwise finishes the last row with its text up to its first clause end, when it comes within
   2.5 s of that row's translation and adds at most 12 CJK characters (a verb-final tail such as
   `…ます。`), and opens a new row with the rest.

A row can thus hold one long Japanese turn and several English sentences, and the Japanese of a
row can show a moment before its English; a source is never shown beside a translation that is
not its own. Nothing is dropped: every chunk lands, whole or split, in rows in arrival order.
Spaces next to Japanese text are removed, and a space is added where an English chunk starts a
new sentence. A row is final 12 s after its last change, or 30 s for a row with a translation
and no source (a late source may still come). The previous sentence-level pairer is kept as
`kana/pairing_v1.py` for replay comparisons.

**`untranslated`**: row `row` has a final source and the model said nothing for it, for example
because the speech was already in the target language (the other person's voice reaching your
microphone). It is sent when an utterance closes after 1.5 s of quiet (see Utterances and latency),
once for each row of that utterance still waiting for a translation, just before that utterance's
`latency` event. The app then shows the row as settled instead of pending. It is not sent when an
utterance is closed by the next onset, because the translation may still be on its way. If a
translation arrives later after all, a `transcript` event fills the row as usual.
```json
{"t": 1794481315.120, "ev": "untranslated", "dir": "out", "row": 5}
```

**`latency`**: sent once per utterance, when it closes. Either field is `null` when it could not
be measured. The definitions are below.
```json
{"t": 1794481311.642, "ev": "latency", "dir": "in", "onset_to_audio_ms": 2998, "src_final_to_dst_final_ms": 403}
```

**`audio`**: sent every second for each direction. All values are cumulative except
`latency_ms`.
```json
{"t": 1794482210.433, "ev": "audio", "dir": "in", "sent_s": 5.2, "recv_s": 10.0, "gated_s": 15.5, "latency_ms": 2892, "usd": 0.00245}
```

| Field | Meaning |
|---|---|
| `sent_s` | Seconds of audio sent to the model: chunks sent × 0.1 s. |
| `recv_s` | Seconds of audio received from the model: bytes ÷ 48,000 (24 kHz int16). This includes the silence the model streams between translations, which is not billed. |
| `gated_s` | Seconds of captured audio not sent because the voice-activity detector judged it silence. |
| `latency_ms` | The running median of `onset_to_audio_ms` for this direction, or `null` before the first measurement. |
| `usd` | The running cost of this direction, computed from the server's token counts, not from seconds. See Cost. |
| `est` | Present and `true` only when `usd` is priced from audio sent rather than server counts (`--provider openai`). |

**`usage`**: the server's token counts for a direction changed. Counts are cumulative for the
run. `model` is the model the direction actually uses, and `usd` is priced at that model's audio
rates (see Cost). `in_text_tokens` is informational: the general Live model used by
`--register business` also bills text input for its instruction and context, and that is not in
`usd`.
```json
{"t": 1794482202.427, "ev": "usage", "dir": "in", "model": "gemini-3.5-live-translate-preview", "in_audio_tokens": 100, "out_audio_tokens": 100, "usd": 0.00245, "in_text_tokens": 0}
```
When a direction uses a model with no known rate, the engine prices it at Live Translate's rates
and sends one non-fatal `error` saying so.

With `--provider openai` the server reports no usage, so the engine prices the audio it sent
($0.034 per minute) and marks the figure `est: true`. The event is sent once per second of audio
sent, carries `sent_s` instead of token counts, and the `audio` event carries `est: true` too:
```json
{"t": 1794482202.427, "ev": "usage", "dir": "in", "model": "gpt-realtime-translate", "sent_s": 12.0, "usd": 0.0068, "est": true}
```

**`error`**: with `fatal: true` the engine is exiting with code 2. With `fatal: false` it keeps
running, for example after an unknown command.
```json
{"t": 1794479734.739, "ev": "error", "fatal": true, "text": "No input device matching \"BlackHole 16ch\" (run with --list-devices to see what is available)"}
```

**`bye`**: sent just before a clean exit.
```json
{"t": 1794481258.48, "ev": "bye"}
```

### Device list

`--list-devices --json` prints one line and exits:
```json
{"inputs": [{"index": 2, "name": "BlackHole 2ch"}, {"index": 3, "name": "MacBook Pro Microphone"}], "outputs": [{"index": 2, "name": "BlackHole 2ch"}, {"index": 4, "name": "MacBook Pro Speakers"}]}
```

### Cost

Audio is about 25 tokens per second. Prices are per million audio tokens and live in one table,
`AUDIO_RATES_PER_M` in `kana/session.py`:

| Model | Input | Output |
|---|---|---|
| `gemini-3.5-live-translate-preview` | $3.50 | $21.00 |
| `gemini-3.8-live` | $3.00 | $12.00 |
| `gpt-realtime-translate` | $0.034 per minute of audio sent, in `AUDIO_RATES_PER_MIN` | |
| any other model | priced as Live Translate, with one non-fatal `error` event | |

The app shows yen at a constant ¥150 per dollar, marked as approximate.

The engine counts cost from the `usage_metadata` the server attaches to its messages. Every
message is a delta, and the engine sums them per direction:

- **Live Translate** sends a report every 1 to 2 s while audio arrives: 25 or 50 audio tokens in
  and the same number out.
- **The general Live model** sends one report per turn. One example turn had 283 audio tokens in,
  390 text tokens in and 103 audio tokens out. The 103 matches the 4.1 s of speech it returned.

**Silence the engine does not send is not billed**, even though Live Translate streams silence
back for as long as the session is open. The measurements below come from 2026-11-12, inbound
only, on a 3 s Japanese sentence with 8 s of silence on each side:

| Run | sent_s | recv_s | Server: audio tokens in | Server: audio tokens out | recv_s × 25 | usd |
|---|---|---|---|---|---|---|
| 22 s, `--vad off` | 20.7 | 18.2 | 500 | 500 | 455 | 0.01225 |
| 22 s, `--vad auto` | 5.2 | 10.0 | 100 | 100 | 250 | 0.00245 |
| 75 s, `--vad auto` | 5.2 | 63.0 | 100 | 100 | 1,575 | 0.00245 |

Live Translate bills output in step with the input it is sent: silence that is sent is billed both
ways. All of the 75 s run's token reports arrived during the 5.2 s of speech. The 58 s of silence
streamed back after it added nothing. So `recv_s` overstates cost, and the engine needs no
idle-close policy. Voice-activity gating cut this run's cost by 80%. `sent_s` and `recv_s` remain
as audio counters. `usd` and the `usage` event are the cost figures.

The server's counts are what the engine shows. The Google Cloud billing console remains the final
word.

## OpenAI provider

`--provider openai` runs each direction on OpenAI's realtime translation model,
`gpt-realtime-translate` (`kana/openai_session.py`, the
[translation guide](https://developers.openai.com/api/docs/guides/realtime-translation)). It is a
websocket to `wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate`, wrapped
so the same `Direction` code runs: voice gate, utterances, latency, pairing, transcripts, playback
catch-up and the JSON events are unchanged.

- **Session**: one per direction, configured with `session.audio.output.language` = the target
  language's base code (`ja`, `en`). The source language is detected. The model stays silent when
  the speech is already in the target language.
- **Audio in**: the 16 kHz chunks are resampled to 24 kHz PCM16 and sent as
  `session.input_audio_buffer.append`. The voice gate still applies (`--vad auto`). OpenAI's guide
  asks for continuous audio including silence; `--vad off` does that, at the cost of billing the
  silence. There is no stream-end message, so the gate's `audio_stream_end` is not sent; the 2 s
  hangover is the only end-of-speech signal.
- **Audio out**: `session.output_audio.delta`, 24 kHz PCM16, into the same playback queue.
- **Transcripts**: `session.output_transcript.delta` becomes `kind: dst`. `kind: src` comes from
  `session.input_transcript.delta`, which the engine turns on with input transcription
  (`gpt-realtime-whisper`, the model the guide names). Whether OpenAI bills that transcription
  separately is not documented.
- **No register control, no voice choice, no instruction.** The voice follows the speaker's tone
  but is not a copy of it. `--register business` is refused.
- **Reconnects**: there is no session resumption. A dropped socket or an `error` event starts a
  fresh session with the same 1, 2, 4 s backoff, and the `session` events are the same. On exit
  the engine sends `session.close`.
- **Cost**: $0.034 per minute of audio sent, per direction (about $2 per hour of speech with the
  gate on), reported with `est: true` (see `usage`). OpenAI returns no usage counts on this
  endpoint, so whether sent silence is billed in full could not be read from the API.

## Voice-activity gating

Capture is cut into 100 ms chunks at 16 kHz. Each chunk's level is its int16 RMS.

- **Speech** is a chunk whose level is above both `--vad-threshold` and three times the noise
  floor.
- **The noise floor** is the lowest chunk level of the previous 5 s. Until 5 s of history exist it
  counts as zero, so speech at the very start of a stream still opens. Steady background noise
  above the threshold therefore stops counting as speech after at most 5 s.
- **Onset** is the first speech chunk after silence. The last 300 ms of gated chunks are sent
  with it as a pre-roll, so word starts are not clipped.
- **Hangover**: after the last speech chunk, audio keeps being sent for `--vad-hangover` (2 s).
  Then `audio_stream_end` is sent once and sending stops until the next onset.
- **Keepalive**: when the gate has sent nothing for 20 s while a session is up, one 100 ms chunk
  of PCM16 silence is sent, and again every 20 s after that. Without it Gemini closed an inbound
  session after about 4 minutes of a silent meeting with error 1008 "Session closed due to client
  inactivity" (2026-11-13), and the reconnect lost a second or two of speech. The Live API docs
  name no inactivity window, so 20 s is our choice, not a documented limit. The silence is billed
  like any input audio and counted in `sent_s`: 0.1 s per 20 s, about 0.5 % of the audio the gate
  holds back. It is never speech: no onset, no utterance, no `latency` event.
- **While muted** (outbound with push-to-talk off), no microphone audio is sent and nothing counts
  as gated. The keepalive still runs, with the same zero-filled chunks, so a long-muted outbound
  session is not closed as idle either.
- **With `--vad off`**, every chunk is sent. Onsets are still detected for the latency readout.
- **Chunks captured while a direction is reconnecting** are dropped, never queued, so no chunk is
  sent twice.

The 2 s hangover is measured. With 400 ms or 1 s of trailing audio, the Live Translate model did
not finish the last sentence: "...いいです" became "the weather is nice," and the closing words
were lost. With 2 s and 3 s it finished every time. Re-measured on 2026-11-13 with 16 clips per
direction ([LATENCY.md](LATENCY.md)): at 1 s and 1.5 s the end of a sentence is held back and
spoken at the start of the next utterance, in both directions; sending the trailing silence at
once instead of in real time does not finish the sentence sooner.

Measured on a 3 s Japanese sentence with 8 s of silence on each side, inbound only, 22 s run:

| `--vad` | sent_s | gated_s | Translation |
|---|---|---|---|
| `off` | 20.7 | 0.0 | complete |
| `auto` | 5.2 | 15.9 | complete |

## Playback catch-up

The model streams digital silence around its speech, often in bursts faster than real time. Queued
back-to-back, that silence delays the words behind it. While any audio is still queued for
playback, the engine drops a chunk that is entirely silent and starts an audible chunk at its first
audible sample (any sample above 64). When playback is not behind, nothing is dropped, so pauses
inside speech are kept. On the latency benchmark this brings the first translated audio about
0.3-0.4 s earlier and the end of the translation about 0.25-0.3 s earlier in both directions
([LATENCY.md](LATENCY.md)). `--catch-up off` plays everything back-to-back as before. Dumps
(`--dump-in`, `--dump-out`) always hold the model's audio unchanged.

## Audio device dropouts

A capture or playback stream can stop mid-call: the meeting app drops and rejoins, a Bluetooth
headset changes profile, a device's sample rate changes, CoreAudio removes a device for a moment.
The engine watches its streams (`audio.watch_streams`, every 0.5 s). A stream counts as stopped
when PortAudio ended it on its own, its callback raised, it is no longer active, or its callback
has not run for 2 s. Then the engine:

1. sends a non-fatal `error`: `{"fatal": false, "text": "BlackHole 16ch stopped; reopening"}`;
2. closes every stream, re-initialises PortAudio (which lists devices only when it starts, so a
   device that came back is invisible until then) and reopens all streams by device name, with
   waits of 0.5, 1, 2, 4 and then 5 s between tries;
3. when that works, sends a non-fatal `error` "BlackHole 16ch reopened after 3.5 s; translation
   continues";
4. if the streams still cannot be opened 60 s after the device stopped, sends a fatal `error`
   ("BlackHole 16ch stopped and could not be reopened for 60 s (...)") and exits with code 2.

The Live sessions stay connected throughout (their keepalive covers the silence), so translation
resumes with the conversation's context. Translated audio that arrives while the earphones are
being reopened is dropped rather than queued. Overflow and underflow flags are counted, never a
reason to reopen. Each step is a `device` line in the events log. A device that is missing at
start-up is still an immediate fatal error. The behaviour is tested with a fake sounddevice
module (`tests/test_device_reopen.py`); no real device was unplugged.

## Own language coming back

In a meeting room the remote microphone can pick up the English spoken next to it, and Live
Translate then re-voices that English in English in your earphones. For each inbound utterance
(see Utterances and latency) the engine decides from its first input-transcription chunks
whether it is already the language you hear: it is when the chunks so far have at least 3 Latin
words and at most twice as many letters of another script as Latin words; it is not when they
have 6 or more letters of another script (CJK, Hangul, Devanagari, ...) and more than twice as
many as Latin words. A few kana are allowed because the inbound session transcribes as Japanese
and often writes the first English word in kana (measured: "Okay" came out as オッケー, "Sorry" as
さり). Until it is decided the utterance plays as usual. Measured on synthetic speech through the
real model (`tools/replay_tts.py --script mixed`, recording in `tests/data/`): all three English
utterances were recognised and all four Japanese ones not; 0.25, 0.25 and 1.0 s of the
re-voiced English played before the decision, the remaining 2.75–4.0 s each did not.

An utterance decided as your own language is still transcribed and paired; its rows carry
`"echo": true` and, with `--voice-own-language off` (the default), the model's audio for it is
not played (it still counts towards `recv_s` and cost, and still goes to `--dump-in`). If a
chunk with 6 or more letters of the meeting's script follows in the same utterance (no pause
between the two speakers), playback resumes and the row's later events say `"echo": false`. The next utterance
is decided afresh. Each decision is an `echo` line in the events log.

The check only runs when the two languages can be told apart by script: a listener language
written in Latin script (`--in en`, `es`, `fr`, `de`, ...) against a meeting language that is
not (`--out ja`, `zh`, `ko`, `hi`, ...), and only inbound. `--in en --out es`, or a Japanese
listener, is not checked.

## Utterances and latency

An **utterance** runs from a voice-activity onset until the next onset, or until 1.5 s pass with
no new transcript or audible model audio while the speaker is silent. Text and audio that arrive
with no onset, for example right after a reconnect, open an utterance with no onset. When an
utterance closes, its unfinished sentences are flushed into it and a `latency` event is sent.

- **`onset_to_audio_ms`** is the time from the onset to the first audible audio received from the
  model. Audible means any sample above 64. The model streams digital silence between
  translations, and that silence does not count. The value is `null` when there was no onset or
  no audible reply.
- **`src_final_to_dst_final_ms`** is the time from the last source sentence to the last
  translated sentence of the utterance. It is `null` when either is missing, or when the
  translation finished before the source transcript did.

## Saved transcripts

At start the engine creates `<save-dir>/transcripts/YYYY-MM-DD-HHMM.md` and `.srt`, named by
local start time. If those names exist, it adds `-2`, `-3` and so on. The rows are the same
rows the app shows (see Pairing). A row is appended and flushed once it is final, 12 s after its
last change (30 s for a row still without its source), and all rows when the run ends, so a
crash loses at most the last 30 s of rows; the events log beside them loses nothing.

Markdown, with ↓ for inbound and ↑ for outbound:
```markdown
# kana transcript 2026-11-12 20:01

ja ↔ en

| Time | Dir | Source | Translation |
|---|---|---|---|
| 20:01:44 | ↓ | こんにちは。今日は天気がいいですね。 | Hello. Today the weather is nice, isn't it? |
```

SRT: an index, a time range relative to the start of the run from the row's first sentence to
its last (at least 0.5 s long), and the text "source → translation":
```
1
00:00:08,144 --> 00:00:13,850
こんにちは。今日は天気がいいですね。 → Hello. Today the weather is nice, isn't it?
```

### Events log (`.events.jsonl`)

Beside the two files the engine writes `YYYY-MM-DD-HHMM.events.jsonl` (`kana/eventlog.py`), the
raw record of the call: what the server sent and when, so a pairing can be replayed and diffed
offline. It is written only when transcripts are saved (not with `--no-save`), flushed per line,
and never holds audio, resumption handles or keys. It contains the transcribed text, so it is as
private as the transcript.

One JSON object per line: `t` (unix seconds, 3 decimals), `dir` (`in` or `out`; absent for
engine-wide lines) and `ev`, plus small fields:

| `ev` | Fields | When |
|---|---|---|
| `start` | `model`, `in_lang`, `out_lang`, `dirs`, `provider` | the engine started (engine-wide) |
| `connected` | `n` (connection count), `resumed` | a session is up |
| `input_transcription`, `output_transcription` | `text` (the chunk as sent), `fin` (only when the server set `finished`) | each transcription chunk |
| `interim_input_transcription` | `text` | an interim input chunk, if the server sends one |
| `audio` | `bytes`, `audible` | each audio chunk from the model (digital silence is `audible: false`) |
| `turn_complete` | `reason` (if the server gave one) | the model ended a turn |
| `generation_complete`, `interrupted`, `waiting_for_input` | | the model's other turn signals |
| `usage` | `prompt`, `response`, `total` | a usage report: the server's token counts as sent |
| `session_resumption_update` | `resumable`, `handle` (whether a new handle came, never the handle) | each resumption update |
| `go_away` | `time_left` | the server announced a handover |
| `setup_complete`, `voice_activity`, `voice_activity_detection_signal`, `tool_call` | | other server message kinds, by name |
| `closed` | `reason` (`go_away`, `session closed`, `error: ...` with the close code, or `stopped`) | a connection ended |
| `reconnecting` | `reason`, `delay` (s) | a reconnect is about to be tried |
| `stream_end` | `why` (`vad` or `mute`) | the engine sent `audio_stream_end` |
| `keepalive` | | a 100 ms silence keepalive was sent |
| `utterance_open` | `seq`, `onset` (false when opened by text or audio with no onset) | an utterance started |
| `utterance_close` | `seq`, `quiet` | an utterance closed (`quiet`: after 1.5 s of quiet) |
| `device` | `state` (`open`, `lost`, `reopen_failed`, `reopened`, `gone`), `name`, and per state `kind`, `reason`, `xruns`, `attempt(s)`, `after_s` | an audio device's lifecycle (engine-wide; see Audio device dropouts) |
| `transcript` | `kind`, `text`, `row`, `row_text`, `merge_into` | every `transcript` op the pairer emitted, as sent to the app |
| `untranslated` | `row` | an `untranslated` event was sent |
| `echo` | `seq` (utterance), `echo`, `play`, `words` or `why` | an inbound utterance was decided to be (or, with `echo: false` and `why`, no longer to be) the listener's own language |
| `stopped` | | the direction stopped |
| `exit` | `reason` (`quit`, `eof`, `stopped`, or the exception name, e.g. `KeyboardInterrupt`) | the engine is exiting (engine-wide) |

```json
{"t":1794795033.739,"dir":"in","ev":"input_transcription","text":"本日はお忙しいところ"}
{"t":1794795033.968,"dir":"in","ev":"output_transcription","text":"Thank you very much"}
{"t":1794795034.010,"dir":"in","ev":"audio","bytes":11520,"audible":true}
```

`kana/replay.py` replays one direction of such a file through the engine's own text path and
pairer, at the logged times, and returns the rows and ops. It is the offline harness for pairing
changes (see `tests/test_pairing_v2.py`); from the shell:

```sh
.venv/bin/python -m kana.replay ~/Library/Application\ Support/kana/transcripts/2026-11-16-1115.events.jsonl
.venv/bin/python -m kana.replay <file> --logged   # the rows the app showed during the call
```

A replay seals rows only at logged events, not every 100 ms as the live engine does, so a row can
be saved slightly later than it was live; the rows themselves are the same.

## Tests

```
.venv/bin/python -m pytest              # all tests; the live test needs GEMINI_API_KEY
.venv/bin/python -m pytest -m "not live"  # offline only
```

The offline tests use fake sessions and fake devices. They cover the event encoding, the stdin
commands, the voice-activity detector on synthetic chunks, latency per utterance, the transcript
files, and a reconnect chaos test. That test drops the socket mid-utterance and checks the
resumption handle, that no chunk or output audio is duplicated, the order of the session events,
and that the transcript files stay consistent. The live test translates a synthesised Japanese
sentence through the real API.
