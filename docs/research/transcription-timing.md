# When Live Translate's transcriptions arrive (2026-11-16)

Why did the 2026-11-16 call show the wrong Japanese beside the English in most inbound rows? The
saved transcript suggested that the input (Japanese) transcription arrives 20–30 s late, in big
chunks, while the output (English) streams. This page measures the real arrival times with the
engine's new events log (`docs/ENGINE.md`, "Events log").

**All numbers below come from synthetic speech** (macOS `say`, voices Kyoko and Eddy (Japanese)),
not from a real call. They were sent through the real engine and the real model
(`gemini-3.5-live-translate-preview`, Developer API, inbound ja→en, `--in-file` paced in real
time, translated audio to BlackHole 2ch, so nothing was audible). Reproduce with
`tools/replay_tts.py`. The three recordings are in `tests/data/` and are replayed by
`tests/test_pairing_v2.py`.

| Run | Script | Length | Input chunks | Output chunks |
|---|---|---|---|---|
| clean | 19 finished sentences (です・ます), back-channels, pauses of 0.3–1.0 s, two gaps of 2.5–3 s | 125.8 s | 122 | 112 |
| runon | 31 clauses ending in て / けど / ので: long turns with few finished sentences, back-channels spoken over the main speaker, same pauses and gaps | 99.6 s | 95 | 93 |
| runon-2 | the same WAV again, with the first pairing v2 running live | 99.6 s | 95 | 90 |

## Findings

1. **The input transcription streams; it is not late.** One input chunk arrives about every
   second (gap between input chunks: median 1.00–1.01 s, p90 1.05–1.07 s, max 2.9 s, all three
   runs) while the person speaks. It is not held until a turn ends.
2. **Each input chunk comes just before its output chunk.** The output transcription of a chunk
   follows it by 0.26–0.28 s (median), p90 0.31–0.35 s, at most 0.52 s, in all three runs. The
   streams interleave 1:1: 105 of 113 runs of input chunks (clean), 89 of 92 (runon) and 85 of 90
   (runon-2) are a single chunk followed by a single output chunk; the rest are two or three
   input chunks followed by one output chunk (the model translated them together). There are
   no N:1 chunks of several sentences. The same WAV gives slightly different wording each run.
3. **There are no turns.** In 325 s of speech the server sent no `turn_complete`, no
   `generation_complete` and no `interrupted`, not even across 2.5–3 s gaps after which the
   engine sent `audio_stream_end`. The `finished` flag of the transcriptions is never set.
   The model also sends no voice-activity messages. Grouping rows by the model's turn signals is
   therefore impossible on Live Translate.
4. **What arrives "late" is the engine's own sentence buffer.** The engine (v1) passed text to the
   pairer only when it ended a sentence (`。？！`). Japanese spoken in run-on clauses has no `。` for
   a long time: in the runon recordings the buffer held the source for up to 32.0 s (25.6 s for
   173 characters, 32.0 s for 202 characters), while the English, which ends sentences often,
   was flushed every 1–8 s. The source then reached the pairer as one large sentence covering
   several English rows, which is exactly the 26 s case of the call. The saved transcript of the
   call agrees (aggregate counts only): 74 % of its Japanese characters were in "sentences" of 60
   or more characters between two sentence ends, 70 of them 120 characters or more, the longest
   797, that is, minutes of speech without a `。`.
5. **Back-channels.** A back-channel by the other voice after a pause is transcribed and
   translated as its own chunk pair (はい。→ "Yes."). One spoken over the main speaker
   (うん during a sentence) was not transcribed at all in these runs: the model followed the
   louder voice.

### What v1 made of it

Replaying the recordings through the v1 pairer (the call's behaviour) and through v2:

| Recording | Pairer | Rows | Both sides | English only | Anchors right |
|---|---|---|---|---|---|
| clean | v1 | 29 | 21 | 6 | 9 / 19 |
| clean | v2 | 25 | 25 | 0 | 19 / 19 |
| runon | v1 | 24 | 12 | 12 | 7 / 18 |
| runon | v2 | 15 | 15 | 0 | 18 / 18 |
| runon-2 | v1 | 21 | 12 | 9 | 10 / 17 |
| runon-2 | first v2, live | 16 | 16 | 0 | 15 / 17 |
| runon-2 | v2 | 16 | 16 | 0 | 17 / 17 |

"Anchors" are hand-checked pairs of a Japanese fragment and the English fragment that translates
it (`tests/test_pairing_v2.py`); an anchor is right when both are in the same row. The v1 replay
reproduces the rows the engine emitted live during the first two runs. In runon-2 the first v2
ran live: a 175-character turn ended with a verb-final tail and one more English sentence for
it ("Right?"); a size bound kept that sentence out of the long row, and the next two
back-channel rows were shifted by one. The rules were changed (spec, rule T2) and the replay of
the same recording is right.

## Consequences for pairing

- Feed the pairer every transcription chunk as it arrives, never a buffered sentence.
- Pair by arrival: a translation chunk belongs with the source chunk that came just before it.
  Cut rows where the English ends a sentence; let a short verb-final tail of the Japanese
  (`…ます。`) finish the row it belongs to.
- No turn signals to rely on; the voice-activity utterance (our own) does not line up with the
  model's output either, so it is not a row boundary.
- A late source is not expected from Live Translate, but other providers may send one (the
  OpenAI realtime translation API's transcript timing is unmeasured); v2 keeps a bounded path for
  it.

The design is in `docs/superpowers/specs/2026-11-16-pairing-v2.md`.

## Not measured

- Real meeting audio: several speakers, Zoom's codec, crosstalk, noise. The call's transcript
  is consistent with the findings above but has no raw timing; the next real call will (events
  log).
- The outbound direction (en→ja) and `--register business` (`gemini-3.8-live`, which does send
  turns), and `--provider openai`.
