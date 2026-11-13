"""Latency benchmark: replays a fixed clip set through kana's real Direction
(VAD gate, Live session, transcripts) against the live API and measures, per
clip, what a listener would hear.

    .venv/bin/python tools/latency_bench.py --label baseline --runs 3
    .venv/bin/python tools/latency_bench.py --label chunk40 --chunk-ms 40 --runs 3
    .venv/bin/python tools/latency_bench.py --label openai --provider openai --runs 3   # gpt-realtime-translate
    .venv/bin/python tools/latency_bench.py --report            # summary of all saved runs

Timing model (all on one monotonic clock):
- capture: chunk i of the WAV is handed to the engine at start + (i+1) * chunk,
  the moment a real input device would deliver it (the block must fill first);
- speech onset / end: the first / last 10 ms window of the clip above the
  speech level, at its real-time position;
- playback: received 24 kHz audio is played back-to-back like kana's Ring
  (start = max(arrival, end of the previous chunk)), so streamed silence that
  queues ahead of speech counts. Device output latency is not included.

Metrics per clip:
- onset_ms: speech onset -> first audible translated sample is played;
- tail_ms:  end of speech -> last audible translated sample has been played.

Each run is one Live session per direction with all clips in sequence (as in a
meeting); between clips silence is fed until the translation has gone quiet.
Results go to tools/bench_out/<label>/<run>.json (ignored by git); --report
prints medians / p90 and transcripts per label.

The API key is read from GEMINI_API_KEY, or OPENAI_API_KEY with --provider openai
(environment first, then the main checkout's .env or --env-file); it is never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kana import audio, backend  # noqa: E402
from kana.openai_session import OPENAI_MODEL, OpenAIDirection  # noqa: E402
from kana.session import DEFAULT_MODEL, Direction  # noqa: E402
from kana.vad import DEFAULT_HANGOVER_MS, VAD  # noqa: E402

OUT_DIR = ROOT / "tools" / "bench_out"
CLIP_DIR = ROOT / "tools" / "bench_clips"

# (id, kind, text). A list of texts is joined with PAUSE_S of silence: a pause mid-thought.
PAUSE_S = 0.9
CLIPS = {
    "en": [
        ("en-short", "short", "Good morning, everyone."),
        ("en-q", "short", "Can you hear me?"),
        ("en-med", "medium", "I think we should move the launch to the second week of December."),
        ("en-med2", "medium", "Our team finished the integration test, and the results look good."),
        ("en-long", "long", "Before we decide on the budget, I would like to review the numbers from last quarter, "
                            "because the cost of cloud services went up by about twenty percent."),
        ("en-tag", "tag", "The approval process is a little slow. Right?"),
        ("en-pause", "pause", ["So the main issue is", "the delivery schedule for the new catalog."]),
        ("en-two", "two", "Thank you for joining today. Let's start with the schedule."),
    ],
    "ja": [
        ("ja-short", "short", "おはようございます。"),
        ("ja-q", "short", "聞こえますか？"),
        ("ja-med", "medium", "来週の会議は水曜日の午後に変更してもよろしいでしょうか。"),
        ("ja-med2", "medium", "テストの結果は概ね良好でしたが、いくつか課題が残っています。"),
        ("ja-long", "long", "予算を決める前に、前の四半期の数字を確認したいと思います。"
                            "クラウドの費用が約二十パーセント上がったからです。"),
        ("ja-tag", "tag", "承認のプロセスが少し遅いですね。そうですよね？"),
        ("ja-pause", "pause", ["一番の問題は", "新しいカタログの納品スケジュールです。"]),
        ("ja-two", "two", "本日はお集まりいただきありがとうございます。では、スケジュールから始めましょう。"),
    ],
    # held-out Japanese set: checks a per-direction setting tuned on "ja"
    "ja2": [
        ("ja2-weather", "short", "こんにちは、今日は天気がいいですね。"),
        ("ja2-thanks", "short", "ありがとうございました。"),
        ("ja2-ok", "short", "はい、大丈夫です。"),
        ("ja2-med", "medium", "資料は明日の朝までにメールでお送りします。"),
        ("ja2-neg", "medium", "その件については、まだ社内で確認できていません。"),
        ("ja2-long", "long", "来月から新しいシステムに移行する予定ですが、移行の前に全てのデータをバックアップする必要があります。"),
        ("ja2-tag", "tag", "価格が少し高いと思います。どうでしょうか？"),
        ("ja2-pause", "pause", ["それについては", "来週もう一度話し合いましょう。"]),
    ],
}
VOICES = {"en": "Samantha", "ja": "Kyoko"}
# Direction -> (source language, target language)
DIRS = {"out": ("en", "ja"), "in": ("ja", "en")}

SPEECH_RMS = 300.0       # 10 ms window level that counts as speech in the clip
LEAD_S = 1.5             # silence before the first clip
QUIET_DONE_S = 2.5       # a clip is done when no audible audio was played for this long ...
MIN_AFTER_S = 3.0        # ... and at least this long after its speech end
MAX_AFTER_S = 15.0       # give up waiting after this long
COST_STOP_USD = 5.0


# --- clips --------------------------------------------------------------------

def _say(text: str, voice: str, path: Path) -> np.ndarray:
    aiff = path.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                    "-sample_fmt", "s16", str(path)], check=True)
    aiff.unlink()
    return np.frombuffer(audio.read_wav_16k(str(path)), dtype="<i2")


def make_clips(lang: str, clip_set: str | None = None) -> list[dict]:
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    clips = []
    for cid, kind, text in CLIPS[clip_set or lang]:
        path = CLIP_DIR / f"{cid}.wav"
        parts = text if isinstance(text, list) else [text]
        if not path.exists():
            pcm = []
            for i, t in enumerate(parts):
                if i:
                    pcm.append(np.zeros(int(PAUSE_S * 16000), dtype=np.int16))
                pcm.append(_say(t, VOICES[lang], CLIP_DIR / f"{cid}.part{i}.wav"))
                (CLIP_DIR / f"{cid}.part{i}.wav").unlink()
            x = np.concatenate(pcm)
            import wave
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(x.astype("<i2").tobytes())
        x = np.frombuffer(audio.read_wav_16k(str(path)), dtype="<i2")
        on, off = speech_span(x)
        clips.append({"id": cid, "kind": kind, "text": " ".join(parts), "pcm": x.tobytes(),
                      "speech_on_s": on, "speech_off_s": off})
    return clips


def speech_span(x: np.ndarray, rate: int = 16000) -> tuple[float, float]:
    w = rate // 100
    n = len(x) // w
    lv = np.sqrt((x[:n * w].astype(np.float32).reshape(n, w) ** 2).mean(axis=1))
    idx = np.nonzero(lv > SPEECH_RMS)[0]
    return idx[0] * w / rate, (idx[-1] + 1) * w / rate


# --- run ------------------------------------------------------------------------

class Recorder:
    """Stands in for the playback queue: timestamps every model audio chunk and
    plays it back-to-back on a virtual clock."""

    def __init__(self, clock):
        self.clock = clock
        self.cursor = 0.0
        self.chunks = []  # (arrival, play_start, n_samples, first_audible_idx, last_audible_idx)

    def put_nowait(self, data: bytes) -> None:
        now = self.clock()
        x = np.frombuffer(data, dtype="<i2")
        start = max(now, self.cursor)
        self.cursor = start + len(x) / 24000
        loud = np.nonzero(np.abs(x.astype(np.int32)) > 64)[0]
        self.chunks.append((now, start, len(x), int(loud[0]) if len(loud) else None,
                            int(loud[-1]) if len(loud) else None))

    def last_audible_play_end(self) -> float | None:
        for arr, start, n, a, b in reversed(self.chunks):
            if b is not None:
                return start + (b + 1) / 24000
        return None


class _Pieces:
    """Mixin: timestamps transcript pieces."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pieces = []  # (t, kind, text)

    def _add(self, kind, text):
        self.pieces.append((self.clock(), kind, text))
        super()._add(kind, text)


class BenchDirection(_Pieces, Direction):
    pass


class OpenAIBenchDirection(_Pieces, OpenAIDirection):
    pass


def main_checkout_env() -> Path:
    """.env of this checkout, or of the main checkout when run from a git worktree."""
    if (ROOT / ".env").exists():
        return ROOT / ".env"
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    common = r.stdout.strip()
    return Path(common).parent / ".env" if r.returncode == 0 and common else ROOT / ".env"


def make_connect(args):
    if args.provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
            load_dotenv(Path(args.env_file))
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit(f"OPENAI_API_KEY is not set (looked in the environment and {args.env_file})")
        from kana.openai_session import make_connect as openai_connect
        return openai_connect(os.environ["OPENAI_API_KEY"])
    project = None
    if args.backend == "vertex":
        project = backend.gcp_project(args.gcp_project)
    elif not os.environ.get("GEMINI_API_KEY"):
        from dotenv import load_dotenv
        load_dotenv(Path(args.env_file))
    return backend.make_client(args.backend, project).aio.live.connect


def live_options(args) -> dict | None:
    if not args.aad:
        return None
    from google.genai import types
    a = json.loads(args.aad)
    aad = types.AutomaticActivityDetection(**a)
    return {"realtime_input_config": types.RealtimeInputConfig(automatic_activity_detection=aad)}


async def run_direction(args, dkey: str, connect) -> dict:
    src, dst = DIRS[dkey]
    clips = make_clips(src, args.set if args.set and args.set.startswith(src) else None)
    clock = time.monotonic
    rec = Recorder(clock)
    in_q: asyncio.Queue = asyncio.Queue(maxsize=200)
    vad = VAD(gate=args.vad == "auto", hangover_ms=args.hangover_ms, chunk_ms=args.chunk_ms, flush_ms=args.flush_ms)
    cls = OpenAIBenchDirection if args.provider == "openai" else BenchDirection
    d = cls(dkey.upper(), src, dst, args.model, in_q, rec, connect=connect, out=lambda *_: None,
                       vad=vad, clock=clock, live_options=live_options(args))
    task = asyncio.create_task(d.run())
    cb = 16000 * args.chunk_ms // 1000 * 2
    silence = bytes(cb)
    t_conn = clock()
    while d.session is None:
        if clock() - t_conn > 20:
            task.cancel()
            raise RuntimeError("no session after 20 s")
        await asyncio.sleep(0.01)
    connect_ms = round((clock() - t_conn) * 1000)
    t0 = clock()
    i = 0  # chunks fed

    async def feed(chunk: bytes):
        nonlocal i
        i += 1
        await asyncio.sleep(max(0.0, t0 + i * args.chunk_ms / 1000 - clock()))  # the block fills, then arrives
        audio.put_latest(in_q, chunk.ljust(cb, b"\0"))

    windows = []
    for _ in range(round(LEAD_S * 1000 / args.chunk_ms)):
        await feed(silence)
    for c in clips * args.loops:
        start_t = t0 + i * args.chunk_ms / 1000  # real-time position of the clip's first sample
        pcm = c["pcm"]
        for k in range(0, len(pcm), cb):
            await feed(pcm[k:k + cb])
        on_t, off_t = start_t + c["speech_on_s"], start_t + c["speech_off_s"]
        while True:  # silence until the translation has finished playing
            await feed(silence)
            now = clock()
            last = rec.last_audible_play_end() or 0.0
            since = now - off_t
            if since >= MAX_AFTER_S or (since >= MIN_AFTER_S and last <= now - QUIET_DONE_S
                                        and rec.cursor <= now):
                break
        windows.append((c, start_t, on_t, off_t, clock()))
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    base = t0
    return {"dir": dkey, "connect_ms": connect_ms, "tokens": d.tokens, "usd": d.usd(),
            "sent_s": round(d.bytes_sent / 32000, 1),
            # raw model audio, for re-simulating playback policies offline:
            # [arrival_s, n_samples, first_audible_idx, last_audible_idx]
            "chunks": [[round(a - base, 4), n, f, l] for a, _, n, f, l in rec.chunks],
            "windows": [{"id": c["id"], "kind": c["kind"], "text": c["text"],
                         "start": round(s0 - base, 4), "on": round(on - base, 4), "off": round(off - base, 4),
                         "end": round(e - base, 4),
                         "src": "".join(p[2] for p in d.pieces if s0 <= p[0] < e and p[1] == "in").strip(),
                         "dst": "".join(p[2] for p in d.pieces if s0 <= p[0] < e and p[1] == "out").strip()}
                        for c, s0, on, off, e in windows]}


def play(chunks, policy: str = "ring", backlog_s: float = 0.0):
    """Play times of [arrival, n, first, last] chunks. ring = kana's Ring
    (everything back-to-back); skip = inaudible chunks, and the leading silence
    of audible ones, are dropped while more than backlog_s is queued."""
    cursor, out = 0.0, []
    for arr, n, f, l in chunks:
        start = max(arr, cursor)
        if policy == "skip" and cursor - arr > backlog_s:
            if f is None:
                out.append(None)
                continue
            n, l, f = n - f, l - f, 0  # play from the first audible sample
        cursor = start + n / 24000
        out.append(None if f is None else (start + f / 24000, start + (l + 1) / 24000))
    return out


def clip_metrics(dr: dict, policy: str = "ring", backlog_s: float = 0.0) -> list[dict]:
    times = play(dr["chunks"], policy, backlog_s)
    res = []
    for w in dr["windows"]:
        aud = [(c, t) for c, t in zip(dr["chunks"], times) if w["start"] <= c[0] < w["end"] and t is not None]
        res.append({**w,
                    "onset_ms": round((aud[0][1][0] - w["on"]) * 1000) if aud else None,
                    "tail_ms": round((aud[-1][1][1] - w["off"]) * 1000) if aud else None,
                    "first_arrival_ms": round((aud[0][0][0] - w["on"]) * 1000) if aud else None,
                    "last_arrival_ms": round((aud[-1][0][0] - w["off"]) * 1000) if aud else None,
                    "out_audio_s": round(sum(c[3] - c[2] + 1 for c, _ in aud) / 24000, 2)})
    return res


def summarize(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None, None, 0
    v.sort()
    p90 = v[min(len(v) - 1, int(np.ceil(0.9 * len(v))) - 1)]
    return round(statistics.median(v)), p90, len(v)


def config_of(args) -> dict:
    return {"provider": args.provider, "model": args.model, "chunk_ms": args.chunk_ms, "hangover_ms": args.hangover_ms, "vad": args.vad, "flush_ms": args.flush_ms,
            "aad": args.aad, "loops": args.loops, "set": args.set, "backend": args.backend,
            "location": backend.VERTEX_LOCATION if args.backend == "vertex" else None}


async def main_async(args) -> None:
    connect = make_connect(args)
    out = OUT_DIR / args.label
    out.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for prev in OUT_DIR.glob("*/*.json"):
        with contextlib.suppress(Exception):
            spent += sum(x["usd"] for x in json.loads(prev.read_text())["dirs"])
    for r in range(args.runs):
        res = {"label": args.label, "config": config_of(args), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
               "commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                                        capture_output=True, text=True).stdout.strip(), "dirs": []}
        for dkey in args.dirs.split(","):
            await asyncio.sleep(args.gap_s)  # back-to-back session creations are slow to first audio
            if spent > COST_STOP_USD:
                raise SystemExit(f"stopping: bench spend so far ${spent:.2f} > ${COST_STOP_USD}")
            dr = await run_direction(args, dkey, connect)
            spent += dr["usd"]
            res["dirs"].append(dr)
            cm = clip_metrics(dr)
            on = summarize([c["onset_ms"] for c in cm])
            tl = summarize([c["tail_ms"] for c in cm])
            print(f"[{args.label} run{r} {dkey}] onset med {on[0]} p90 {on[1]} | tail med {tl[0]} p90 {tl[1]} "
                  f"| connect {dr['connect_ms']} ms | ${dr['usd']:.4f} (total ${spent:.3f})", flush=True)
        n = len(list(out.glob("*.json")))
        (out / f"run{n:02d}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))


def report(labels: list[str] | None, show_text: bool, policy: str, backlog_s: float, md: bool) -> None:
    total = 0.0
    dirs_ = [p for p in OUT_DIR.iterdir() if p.is_dir()]
    order = labels or [p.name for p in sorted(dirs_, key=lambda p: p.stat().st_mtime)]
    for name in order:
        ldir = OUT_DIR / name
        runs = [json.loads(p.read_text()) for p in sorted(ldir.glob("*.json"))]
        if not runs:
            continue
        cfg = runs[0]["config"]
        if not md:
            print(f"\n## {name}  {cfg}  runs={len(runs)}  playback={policy}")
        cells = []
        for dkey in ("out", "in"):
            drs = [d for r in runs for d in r["dirs"] if d["dir"] == dkey]
            if not drs:
                cells.append("– | – | – | –")
                continue
            clips = [c for d in drs for c in clip_metrics(d, policy, backlog_s)]
            usd = sum(d["usd"] for d in drs)
            total += usd
            on, tl = summarize([c["onset_ms"] for c in clips]), summarize([c["tail_ms"] for c in clips])
            miss = sum(1 for c in clips if c["onset_ms"] is None)
            # a translation that does not end its sentence was cut (its end usually
            # turns up at the start of the next utterance)
            cut = sum(1 for c in clips if not c["dst"].rstrip().endswith(tuple(".?!。？！")))
            sent = sum(d["sent_s"] for d in drs) / len(drs)
            if md:
                cells.append(f"{on[0]} / {on[1]} | {tl[0]} / {tl[1]} | {cut}/{len(clips)} | {sent:.0f} s, "
                             f"${usd / len(drs):.3f}" + (f", {miss} silent" if miss else ""))
                continue
            print(f"  {dkey}: onset med {on[0]} p90 {on[1]} | tail med {tl[0]} p90 {tl[1]} | n={len(clips)} "
                  f"no-audio={miss} cut={cut} | sent {sent:.1f} s/run | ${usd:.3f}")
            if show_text:
                for c in clips:
                    print(f"    {c['id']:9} on {c['onset_ms']!s:>5} tail {c['tail_ms']!s:>5} | {c['src']} => {c['dst']}")
        if md:
            print(f"| {time.strftime('%Y-%m-%d')} | {runs[0]['commit']} | {name} | {len(runs)} | {policy} | "
                  + " | ".join(cells) + " |")
    print(f"\ntotal spend of the listed runs ${total:.3f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="baseline")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--dirs", default="out,in", help="comma list of out (en->ja) / in (ja->en)")
    p.add_argument("--provider", choices=["gemini", "openai"], default="gemini")
    p.add_argument("--model", help=f"default: {DEFAULT_MODEL}, or {OPENAI_MODEL} with --provider openai")
    p.add_argument("--chunk-ms", type=int, default=audio.CHUNK_MS)
    p.add_argument("--hangover-ms", type=int, default=DEFAULT_HANGOVER_MS)
    p.add_argument("--flush-ms", type=int, default=0, help="digital silence burst sent at the VAD end")
    p.add_argument("--vad", choices=["auto", "off"], default="auto")
    p.add_argument("--aad", help='JSON for AutomaticActivityDetection, e.g. {"silence_duration_ms":300}')
    p.add_argument("--backend", choices=backend.BACKENDS, default="developer")
    p.add_argument("--gcp-project", help="with --backend vertex (default: GOOGLE_CLOUD_PROJECT, then gcloud config)")
    p.add_argument("--env-file", default=str(main_checkout_env()),
                   help=".env with GEMINI_API_KEY / OPENAI_API_KEY (default: this checkout's, else the main checkout's)")
    p.add_argument("--set", help="clip set instead of the direction's default (e.g. ja2, held out)")
    p.add_argument("--loops", type=int, default=1, help="play the clip set this many times in one session (drift)")
    p.add_argument("--gap-s", type=float, default=12.0, help="pause before each new session")
    p.add_argument("--report", action="store_true")
    p.add_argument("--text", action="store_true", help="with --report: per-clip transcripts")
    p.add_argument("--playback", choices=["ring", "skip"], default="ring",
                   help="with --report: simulated playback policy (see play())")
    p.add_argument("--backlog-ms", type=int, default=0, help="with --playback skip")
    p.add_argument("--md", action="store_true", help="with --report: markdown table rows")
    p.add_argument("labels", nargs="*", help="with --report: only these labels")
    args = p.parse_args()
    if args.model is None:
        args.model = OPENAI_MODEL if args.provider == "openai" else DEFAULT_MODEL
    if args.report:
        report(args.labels, args.text, args.playback, args.backlog_ms / 1000, args.md)
        return
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
