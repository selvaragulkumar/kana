# kana engine

The engine is the Python package `kana`. It runs one Gemini Live session per translation
direction and moves audio between your devices and the model. It runs on its own in a terminal,
and the menu-bar app drives it through a JSON-lines protocol on stdin and stdout.

```
python -m kana [flags]             # or the console script: kana [flags]
```

The API key comes from `GEMINI_API_KEY`. The engine reads it from the environment, from `.env`
in the current directory, or from `.env` in the repository root.

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
| `--meet-mic NAME` | `BlackHole 2ch` | The device the meeting app uses as its microphone. |
| `--meet-spk NAME` | `BlackHole 16ch` | The device the meeting app uses as its speakers. |
| `--in LANG` | `en` | The language you hear (BCP-47). |
| `--out LANG` | `ja` | The language the meeting hears (BCP-47). |
| `--model ID` | `gemini-3.5-live-translate-preview` | The Live model. Models without "translate" in the name get a translator system instruction instead. |
| `--register default\|business` | `default` | The outbound Japanese register. `default` keeps Live Translate, with your own voice and your own register: casual English becomes casual Japanese. `business` (opt-in) sends the outbound direction to `gemini-3.8-live` with a keigo instruction, which guarantees です・ます and keigo but uses a stock voice. Inbound always uses `--model`. See [REGISTER.md](REGISTER.md). |
| `--in-file WAV` | none | A 16-bit WAV that replaces the meeting capture. Used for tests and dry runs. It starts playing once its session has connected. |
| `--out-file WAV` | none | A 16-bit WAV that replaces your microphone. Push-to-talk then starts on. |
| `--dump-in WAV` | none | Also writes the inbound translated audio (24 kHz mono) to this file. |
| `--dump-out WAV` | none | Also writes the outbound translated audio to this file. |
| `--only in\|out` | both | Runs a single direction. |
| `--list-devices` | | Lists audio devices and exits. With `--json` it prints one JSON line. |
| `--vad auto\|off` | `auto` | Voice-activity gating of what is sent. With `off`, every chunk is streamed. |
| `--vad-threshold RMS` | `200` | The absolute speech level: the int16 RMS of a 100 ms chunk. |
| `--vad-hangover MS` | `2000` | How long audio is still sent after speech ends, before the stream end. |
| `--save-dir DIR` | `~/Library/Application Support/kana` | Transcripts are written to `DIR/transcripts/`. |
| `--no-save` | | Saves no transcripts. |
| `--json` | | Runs the JSON-lines protocol described below. |

Exit codes: `0` is a clean exit and `2` is a fatal setup error, such as a missing key, a missing
device or a device that fails to open.

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

Any other line produces a non-fatal `error` event and is otherwise ignored.

### Events (stdout), in the order they first appear

**`ready`**: the devices are open. A direction that is not running is `null`, and so is its model.
A file source is shown as `file <path>`. `model` is the `--model` flag. `in_model` and `out_model`
are the models each direction actually uses, and `register` is the `--register` flag.
```json
{"t": 1794481886.512, "ev": "ready", "in": {"src": "BlackHole 16ch", "sink": "MacBook Pro Speakers"}, "out": {"src": "MacBook Pro Microphone", "sink": "BlackHole 2ch"}, "model": "gemini-3.5-live-translate-preview", "register": "default", "in_model": "gemini-3.5-live-translate-preview", "out_model": "gemini-3.5-live-translate-preview", "in_lang": "en", "out_lang": "ja"}
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

**`transcript`**: one finished sentence. `kind` is `src` for what was heard and `dst` for what
the model spoke. A sentence is flushed when it ends with `. ? ! 。 ？ ！`, when the model ends its
turn, when the connection drops, or when its utterance closes. `final` is always `true`.
```json
{"t": 1794481308.975, "ev": "transcript", "dir": "in", "kind": "src", "text": "こんにちは。今日は天気がいいですね。", "final": true}
{"t": 1794481309.378, "ev": "transcript", "dir": "in", "kind": "dst", "text": "Hello. Today the weather is nice, isn't it?", "final": true}
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
- **While muted** (outbound with push-to-talk off), nothing is sent and nothing counts as gated.
- **With `--vad off`**, every chunk is sent. Onsets are still detected for the latency readout.
- **Chunks captured while a direction is reconnecting** are dropped, never queued, so no chunk is
  sent twice.

The 2 s hangover is measured. With 400 ms or 1 s of trailing audio, the Live Translate model did
not finish the last sentence: "...いいです" became "the weather is nice," and the closing words
were lost. With 2 s and 3 s it finished every time.

Measured on a 3 s Japanese sentence with 8 s of silence on each side, inbound only, 22 s run:

| `--vad` | sent_s | gated_s | Translation |
|---|---|---|---|
| `off` | 20.7 | 0.0 | complete |
| `auto` | 5.2 | 15.9 | complete |

## Utterances and latency

An **utterance** runs from a voice-activity onset until the next onset, or until 1.5 s pass with
no new transcript or audible model audio while the speaker is silent. Text and audio that arrive
with no onset, for example right after a reconnect, open an utterance with no onset. When an
utterance closes, its unfinished sentences are flushed into it, a `latency` event is sent, and a
transcript row is saved.

- **`onset_to_audio_ms`** is the time from the onset to the first audible audio received from the
  model. Audible means any sample above 64. The model streams digital silence between
  translations, and that silence does not count. The value is `null` when there was no onset or
  no audible reply.
- **`src_final_to_dst_final_ms`** is the time from the last source sentence to the last
  translated sentence of the utterance. It is `null` when either is missing, or when the
  translation finished before the source transcript did.

## Saved transcripts

At start the engine creates `<save-dir>/transcripts/YYYY-MM-DD-HHMM.md` and `.srt`, named by
local start time. If those names exist, it adds `-2`, `-3` and so on. A row is appended and
flushed as each utterance closes, so a crash loses at most the utterance in progress.

Markdown, with ↓ for inbound and ↑ for outbound:
```markdown
# kana transcript 2026-11-12 20:01

ja ↔ en

| Time | Dir | Source | Translation |
|---|---|---|---|
| 20:01:44 | ↓ | こんにちは。今日は天気がいいですね。 | Hello. Today the weather is nice, isn't it? |
```

SRT: an index, a time range relative to the start of the run from the utterance's first event to
its last event (at least 0.5 s long), and the text "source → translation":
```
1
00:00:08,144 --> 00:00:13,850
こんにちは。今日は天気がいいですね。 → Hello. Today the weather is nice, isn't it?
```

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
