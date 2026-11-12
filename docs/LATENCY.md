# Latency

How fast kana interprets, how it is measured, and what was tried. The results table is
append-only: add rows, never edit old ones.

## The benchmark

`tools/latency_bench.py` replays a fixed clip set through the engine's real `Direction` (voice
gate, Live session, transcripts) against the live API.

```sh
.venv/bin/python tools/latency_bench.py --label baseline --runs 3        # both directions
.venv/bin/python tools/latency_bench.py --label h1500 --hangover-ms 1500 --dirs out
.venv/bin/python tools/latency_bench.py --report --playback skip --text   # medians, p90, transcripts
.venv/bin/python tools/latency_bench.py --report --md --playback skip baseline h1500  # table rows
```

- **Clips**: 8 English (`out`, en→ja) and 8 Japanese (`in`, ja→en) sentences made with macOS `say`
  (Samantha, Kyoko): short, a question, medium, long, a two-sentence utterance with a short tag
  ("…slow. Right?" / "…遅いですね。そうですよね？"), a 0.9 s pause mid-thought, and two sentences.
  `--set ja2` is a held-out Japanese set used to check a setting tuned on the first. The clips
  are generated into `tools/bench_clips/` (not committed; `say` regenerates them identically).
- **One run** is one Live session per direction with all clips in sequence, like a meeting.
  Between clips, silence is fed until the translation has finished playing. New sessions are
  started 12 s apart.
- **Capture timing**: a chunk reaches the engine when a real input device would deliver it, after
  the block has filled.
- **Playback timing**: the model's audio is played back-to-back on a virtual clock the way kana's
  `Ring` plays it. Every received chunk is saved with its arrival time, so playback policies are
  compared offline on the same recorded stream (`--playback ring|skip`). Device output latency is
  not included.
- **onset** = speech onset → first audible translated sample is played.
  **tail** = end of speech → last audible translated sample has been played.
- **cut** = translations of a clip that do not end their sentence. The rest of the sentence then
  turns up at the start of the next utterance, which also makes that utterance's onset look fast.
  Every cut and every transcript was also read by hand.
- Raw runs (JSON with all chunk timings and transcripts) are kept in `tools/bench_out/` (ignored by
  git).

## Results

Cells are median / p90 in ms over all clips of all runs (8 clips × runs). Cost is per run and
direction, from the server's `usage_metadata`. Commit `f32a3c7` is the engine before this work,
plus the uncommitted benchmark. `ring` is kana's playback before this work; `skip` is the new
catch-up playback.

| Date | Commit | Config | Runs | Playback | out onset | out tail | out cut | out sent, $ | in onset | in tail | in cut | in sent, $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-13 | f32a3c7 | baseline | 3 | ring | 1954 / 3344 | 3624 / 4376 | 0/24 | 46 s, $0.028 | 2360 / 3624 | 2726 / 3367 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | f32a3c7 | baseline-b | 3 | ring | 2184 / 3388 | 3512 / 4329 | 0/24 | 46 s, $0.028 | 2340 / 3540 | 2758 / 3418 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | f32a3c7 | baseline | 3 | skip | 1632 / 2977 | 3384 / 4073 | 0/24 | 46 s, $0.028 | 1961 / 3232 | 2440 / 3296 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | f32a3c7 | baseline-b | 3 | skip | 1856 / 3045 | 3270 / 4050 | 0/24 | 46 s, $0.028 | 1979 / 3223 | 2459 / 3248 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | f32a3c7 | vad-off | 3 | skip | 3205 / 3868 | 3668 / 5030 | 1/24 | 149 s, $0.089 | 3367 / 3612 | 3268 / 3585 | 0/24 | 158 s, $0.095 |
| 2026-11-13 | f32a3c7 | hang1500 | 3 | skip | 1280 / 2962 | 2934 / 3614 | 6/24 | 42 s, $0.025 | – | – | – | – |
| 2026-11-13 | f32a3c7 | hang1500-out-b | 3 | skip | 1486 / 2824 | 2772 / 3411 | 4/24 | 42 s, $0.025 | – | – | – | – |
| 2026-11-13 | f32a3c7 | hang1000 | 3 | skip | 938 / 2873 | 2504 / 3049 | 14/24 | 38 s, $0.023 | 1626 / 2756 | 2314 / 2869 | 0/24 | 47 s, $0.028 |
| 2026-11-13 | f32a3c7 | hang1000-in-b | 3 | skip | – | – | – | – | 1587 / 3124 | 2312 / 2999 | 1/24 | 47 s, $0.028 |
| 2026-11-13 | f32a3c7 | hang1000-in-c (out at 2000) | 3 | skip | 1855 / 3091 | 3163 / 4118 | 0/24 | 46 s, $0.028 | 1572 / 2737 | 2381 / 2983 | 0/24 | 47 s, $0.028 |
| 2026-11-13 | f32a3c7 | ja2-hang2000 (held out) | 3 | skip | – | – | – | – | 2062 / 3204 | 2502 / 3120 | 0/24 | 48 s, $0.029 |
| 2026-11-13 | f32a3c7 | ja2-hang1000 (held out) | 3 | skip | – | – | – | – | 1409 / 2977 | 2115 / 2590 | 3/24 | 40 s, $0.024 |
| 2026-11-13 | f32a3c7 | hang500 | 3 | skip | 984 / 2779 | 2101 / 2504 | 17/24 | 33 s, $0.020 | 867 / 1926 | 1860 / 2191 | 9/24 | 43 s, $0.026, 3 silent |
| 2026-11-13 | f32a3c7 | hang500-flush1500 | 3 | skip | 1576 / 3031 | 3300 / 4087 | 4/24 | 47 s, $0.028 | 1696 / 3173 | 2496 / 3853 | 0/24 | 56 s, $0.034 |
| 2026-11-13 | f32a3c7 | chunk40 | 3 | skip | 2046 / 3107 | 3344 / 4115 | 1/24 | 45 s, $0.028 | 1876 / 3294 | 2499 / 3280 | 0/24 | 54 s, $0.033 |
| 2026-11-13 | f32a3c7 | chunk20 | 3 | skip | 2446 / 3111 | 3219 / 3489 | 3/24 | 45 s, $0.027 | 1984 / 3312 | 2516 / 3569 | 0/24 | 54 s, $0.033 |
| 2026-11-13 | f32a3c7 | translate-aad | 3 | skip | 1518 / 3009 | 3282 / 4276 | 0/24 | 46 s, $0.028 | 1974 / 3244 | 2264 / 3278 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | f32a3c7 | fallback | 3 | skip | 4269 / 9403 | 5015 / 8933 | 0/24 | 46 s, $0.032 | 2461 / 7710 | 2236 / 6279 | 4/24 | 55 s, $0.029, 3 silent |
| 2026-11-13 | f32a3c7 | fallback-tuned | 3 | skip | 3875 / 8958 | 4366 / 7916 | 2/24 | 45 s, $0.035 | – | – | – | – |
| 2026-11-13 | f32a3c7 | drift10min (19 min session) | 1 | skip | 1938 / 3272 | 3100 / 4031 | 0/64 | 364 s, $0.222 | – | – | – | – |
| 2026-11-13 | 0df775c | baseline-c | 3 | skip | – | – | – | – | 2070 / 3439 | 2493 / 3548 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | 0df775c | translate-aad-b | 3 | skip | – | – | – | – | 1924 / 2834 | 2604 / 3252 | 0/24 | 55 s, $0.033 |
| 2026-11-13 | 0df775c | translate-aad-ja2 (held out) | 3 | skip | – | – | – | – | 2152 / 3238 | 2932 / 3282 | 0/24 | 48 s, $0.029 |

### Summary, 2026-11-13

The two baseline sets together (6 runs, 48 clips per direction), on the same recorded streams:

| | out onset | out tail | in onset | in tail |
|---|---|---|---|---|
| before (ring playback) | 2075 / 3388 | 3572 / 4376 | 2354 / 3624 | 2746 / 3418 |
| after (catch-up playback) | 1763 / 3045 | 3334 / 4073 | 1970 / 3232 | 2452 / 3296 |
| floor: first / last audio arrival | 1630 / 2949 | 3118 / 3928 | 1882 / 3139 | 2292 / 2958 |

The remaining time is the model's: the first translated audio reaches the Mac 1.6-1.9 s after
the speaker starts, and the network round trip is about 17 ms.

## What was tried

| Candidate | Source of the value | Result | Decision |
|---|---|---|---|
| **Playback catch-up**: drop streamed silence while playback is behind | Our measurement: the model sends 250 ms chunks in bursts, and the silence ahead of its speech queued in the `Ring` | onset −310 / −380 ms, tail −240 / −290 ms (out / in, median). The span of the translated speech changes by a median of −39 ms (max 320 ms), so pauses inside speech are kept. Transcripts unaffected (playback only). | **Shipped**, default on, `--catch-up off` to disable |
| Catch-up also when playback is not behind (trim every leading silence) | — | a further −60 to −120 ms onset, but it would also shorten pauses between sentences | not shipped |
| Ungated continuous streaming (`--vad off`) | Google's Live Translate example and LiveKit stream continuously ([live-translate](https://ai.google.dev/gemini-api/docs/live-api/live-translate), livekit-plugins-google `gemini_translation.py`) | onset 3.2-3.4 s (+1.5 s), tail +0.3-0.8 s, 3.2× the audio tokens | rejected; the gate with `audio_stream_end` keeps the model's lag low |
| Hangover 1,000 / 1,500 ms out (en→ja) | brief | 14/24 and 6/24 + 4/24 translations cut: the sentence end ("…皆さん。") is spoken at the start of the next utterance | rejected |
| Hangover 1,000 ms in (ja→en) | brief | tail −140 ms, onset −350 ms, but on the held-out set "…いいですね" became "nice," with "isn't it?" in the next utterance in 3 of 3 runs, and the source transcript split ("残ってい" / "ます。") in 3 of 3 runs | rejected; same failure as the original 2 s measurement in ENGINE.md |
| Hangover 500 ms | brief | 17/24 and 9/24 cut, 3 clips lost entirely | rejected |
| Hangover 500 ms + 1,500 ms of digital silence sent at once before `audio_stream_end` | our idea: show the model the trailing silence faster than real time | tail no better than 2 s of real-time hangover (3.30 vs 3.38 s); still 4/24 cut | rejected: the model needs real-time silence |
| Capture chunks 40 ms / 20 ms | [Live API best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices): "chunks of 20ms to 40ms"; the Live Translate page and LiveKit recommend 100 ms | out onset +0.2-0.4 s (40 ms) and +0.6-0.8 s (20 ms), no tail or inbound gain, 1/24 and 3/24 cut | rejected; 100 ms stays (the translate model's documented value) |
| `realtime_input_config` automatic activity detection on the translate model (silence 500 ms, prefix 100 ms, end sensitivity high) | Live API docs; Pipecat/LiveKit defaults for general Live models | first set looked like −180 ms inbound tail (2.26 vs 2.44-2.49 s), but the repeat gave 2.60 s and the held-out set 2.93 vs 2.50 s: noise; out tail unchanged. Not documented for Live Translate. | rejected |
| Fallback `gemini-3.8-live` | brief | onset 4.3 s out, p90 9.4 s; in: 3 clips silent, words dropped ("証人のプロセス") | rejected |
| Fallback with 40 ms chunks + activity detection (silence 500 ms, prefix 100 ms) | [best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices); research notes (2,000 ms+ "increases perceived latency") | onset 3.9 s, p90 9.0 s: still far behind the translate model | `--register business` keeps it; no change |
| Vertex AI in Tokyo | brief | The translate model is served only at location `global` ([Vertex model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-live-translate)); no asia-northeast1. A `global` A/B was not run: application-default credentials need a fresh `gcloud auth application-default login`. | not tested |
| Network | — | TCP connect to generativelanguage.googleapis.com, aiplatform.googleapis.com and asia-northeast1-aiplatform.googleapis.com: 17, 17 and 19 ms (median of 6) | not a lever |
| Sounddevice `latency="low"` | sounddevice docs | Reported device latencies (no stream opened): output low/high 1.3/10.7 ms (BlackHole), 18/27 ms (MacBook speakers); input 10/100 ms (BlackHole 16ch), 33/42 ms (MacBook mic) | not shipped: output gains ≤ 10 ms with an underrun risk; capture of BlackHole 16ch could gain ~90 ms on inbound but was not measured, because measuring needs opening real devices |
| Session drift | research notes (latency creeping up over minutes) | one 19-minute session (8 loops): onset median 1.4, 1.9, 1.9, 1.9, 2.3, 2.1, 1.9, 1.9 s; tail 3.3, 3.3, 3.6, 3.4, 2.8, 2.6, 2.8, 2.9 s; no cuts | no drift; no restart logic needed |

## Spend

The benchmarks on 2026-11-13 used 95 sessions: 192,237 audio tokens in and 129,130 out (plus
33,574 text tokens in on the fallback model), about $3.35 in total at the rates in
`kana/session.py`, including one smoke run.
