"""Measures when Gemini's input and output transcriptions really arrive, on a
synthetic Japanese business monologue (macOS `say`, two voices).

    .venv/bin/python tools/replay_tts.py synth tmp-run/meeting.wav     # WAV + segments JSON, no network
    .venv/bin/python tools/replay_tts.py synth --script runon tmp-run/runon.wav  # run-on turns, overlaps
    .venv/bin/python tools/replay_tts.py synth --script mixed tmp-run/mixed.wav  # English from the room in between
    .venv/bin/python tools/replay_tts.py run tmp-run/meeting.wav \\
        --env-file /path/to/.env --save-dir tmp-run                    # real engine, costs a few cents
    .venv/bin/python tools/replay_tts.py analyze tmp-run/transcripts/<stem>.events.jsonl \\
        --segments tmp-run/meeting.segments.json                       # timing report from the events log

`synth` speaks each line of SCRIPT with `say -o x.aiff` (Kyoko, or Eddy for the
other person), converts it with `afconvert -f WAVE -d LEI16@16000 -c 1` and
joins the lines with the given pauses. Beside the WAV it writes
`<name>.segments.json`: each line's text, voice and start/end in the WAV.

`run` starts the real engine on the WAV (`--only in --in-file`, paced in real
time by kana/audio.py), with its translated audio going to "BlackHole 2ch", a
virtual device nothing listens to: nothing is played on the Mac's speakers. It
checks the device exists first. stdin stays open until the WAV and a tail have
played, then `quit` is sent. Engine stdout goes to `<save-dir>/engine.jsonl`.

`analyze` reads the events log (kana/eventlog.py) and prints, per input
transcription chunk, how long after the output transcription covering the same
speech it arrived, how chunks relate to turn_complete / interrupted, and the
N:1 grouping of chunks onto output sentences.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

KYOKO, EDDY = "Kyoko", "Eddy (Japanese (Japan))"
RATE = 16000
SAY_RATE = 210  # words per minute; a brisk meeting pace (say's default is about 175)

# (voice, text, pause after in s). Our own sentences, in the style of a business meeting:
# long sentences with short pauses, back-channels from the other person, two longer gaps.
SCRIPT = [
    (KYOKO, "本日はお忙しいところお時間をいただきまして、誠にありがとうございます。", 0.6),
    (KYOKO, "早速ですが、前回の打ち合わせでご相談いただいた商品データの整備について、進捗をご報告させていただきます。", 0.5),
    (EDDY, "はい。", 0.4),
    (KYOKO, "まず、先月お預かりした約三千件の商品のうち、仕様の項目が埋まっているものは七割ほどでした。", 0.4),
    (KYOKO, "残りの三割については、メーカーのカタログを読み込んで、寸法や重量、電源の仕様などを補っています。", 0.8),
    (EDDY, "そうですね。", 0.5),
    (KYOKO, "特に時間がかかっているのは、同じ商品でも型番の書き方が社内とメーカーで違っているケースで、ここは人の確認が必要になります。", 0.3),
    (KYOKO, "なので、確認の手順を少し変えて、担当の方が一覧でまとめて承認できるようにしました。", 1.0),
    (EDDY, "なるほど、それは助かりますね。来週の会議までに、どのくらい進みそうですか。", 0.7),
    (KYOKO, "来週の水曜日までには、全体の九割まで埋められる見込みです。", 0.4),
    (KYOKO, "ただ、写真の差し替えについては、まだ権利の確認が取れていないものがあるので、そこは別途ご相談させてください。", 3.0),
    (EDDY, "はい、わかりました。", 0.6),
    (KYOKO, "それから、費用の件ですが、月額の料金は前回お見積もりした金額から変わりません。", 0.5),
    (KYOKO, "初期の設定費用についても、対象のカテゴリーが増えない限りは、追加でいただくことはございません。", 0.9),
    (EDDY, "そうですね。", 0.3),
    (KYOKO, "最後に、来月からの運用体制ですが、弊社側で二名、御社側で一名、窓口になっていただける方をお願いできればと思っております。", 0.6),
    (KYOKO, "週に一度、三十分ほどの定例を設けて、そこで課題を確認していく形を想定しています。", 2.5),
    (EDDY, "はい。承知しました。社内で確認して、担当者を決めておきます。", 0.5),
    (KYOKO, "ありがとうございます。それでは、本日はこのあたりで失礼いたします。", 0.0),
]

# Spontaneous speech: long run-on turns of clauses that end in て / けど / ので, so the
# speaker rarely finishes a sentence, with the other person's back-channels spoken over
# them (a negative pause starts the next line that many seconds before this one ends).
RUNON = [
    (KYOKO, "えーと、それで、前回お話ししたデータの件なんですけど、", 0.4),
    (KYOKO, "あの、先週から少しずつ取り込みを始めていて、", 0.3),
    (KYOKO, "メーカーさんから届いたファイルが、形式がばらばらだったので、", -1.2),
    (EDDY, "うん。", 0.3),
    (KYOKO, "まずそれを揃えるところから、こう、手作業も混ぜながらやっていて、", 0.4),
    (KYOKO, "で、今はだいたい半分ぐらいまで来ているんですが、", 0.3),
    (KYOKO, "残りの半分が、型番の表記が違うものが多くて、そこがちょっと時間がかかりそうな感じなんですよね。", 0.8),
    (EDDY, "そうですね。", 0.5),
    (EDDY, "なるほど、それって、うちの方で何か先に準備しておけば、早くなったりするものなんですか。", 0.6),
    (KYOKO, "あ、そうですね、", 0.3),
    (KYOKO, "もし可能であれば、社内で使っている型番の一覧を、エクセルとかで一度いただけると、", 0.4),
    (KYOKO, "こちらで突き合わせができるので、", -0.9),
    (EDDY, "うん、うん。", 0.2),
    (KYOKO, "かなり早くなると思いますし、", 0.3),
    (KYOKO, "あと、間違いも減らせるので、", 0.4),
    (KYOKO, "そこはぜひお願いできればと思っていて、", 0.3),
    (KYOKO, "で、もう一つだけ確認したいのが、", 0.3),
    (KYOKO, "写真の件なんですけど、", -0.8),
    (EDDY, "はい。", 0.2),
    (KYOKO, "以前いただいた画像の中に、他社さんのロゴが入っているものがいくつかあって、", 0.4),
    (KYOKO, "それをそのまま使っていいのかどうか、", 0.3),
    (KYOKO, "ちょっと判断がつかなかったので、一旦保留にしてあります。", 1.0),
    (EDDY, "はい、はい。", 0.4),
    (EDDY, "それは確認して、また来週お返事します。", 2.5),
    (KYOKO, "ありがとうございます、", 0.3),
    (KYOKO, "あと、来月の定例なんですけど、", 0.3),
    (KYOKO, "今のところ毎週火曜日の午後で考えていて、", 0.4),
    (KYOKO, "もし難しければ、木曜日でも大丈夫なので、", -0.8),
    (EDDY, "うん。", 0.2),
    (KYOKO, "そのあたりはまたメールでご相談させてください。", 0.6),
    (EDDY, "わかりました、じゃあ、そんな感じで進めましょう。", 0.0),
]
# English spoken in the room next to the remote microphone, between Japanese turns (echo check,
# --voice-own-language). Pauses of 2.5 s give each line its own utterance.
SAMANTHA = "Samantha"
MIXED = [
    (KYOKO, "それでは、本日の議題から始めさせていただきます。", 2.5),
    (SAMANTHA, "Sorry, could you share the screen again? I can't see the slides.", 2.5),
    (KYOKO, "はい、少々お待ちください。今、画面を共有します。", 2.5),
    (SAMANTHA, "Okay, I can see it now. Thank you very much.", 2.5),
    (KYOKO, "こちらが先月の数字になります。全体で一割ほど増えています。", 2.5),
    (SAMANTHA, "That's great news, let's look at the details next.", 2.5),
    (KYOKO, "ありがとうございます。では、次のページに進みます。", 0.0),
]
SCRIPTS = {"clean": SCRIPT, "runon": RUNON, "mixed": MIXED}


def say_wav(voice: str, text: str, out: Path, tmp: Path) -> None:
    aiff = tmp / (out.stem + ".aiff")
    subprocess.run(["say", "-v", voice, "-r", str(SAY_RATE), "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", str(aiff), str(out)], check=True)


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return w.readframes(w.getnframes())


def synth(wav: Path, script: str = "clean") -> Path:
    import numpy as np
    wav.parent.mkdir(parents=True, exist_ok=True)
    pcm, segs, at = np.zeros(0, dtype=np.int32), [], 0  # at: sample where the next line starts
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for i, (voice, text, pause) in enumerate(SCRIPTS[script]):
            part = tmp / f"line{i:02d}.wav"
            say_wav(voice, text, part, tmp)
            data = np.frombuffer(read_pcm(part), dtype="<i2").astype(np.int32)
            end = at + len(data)
            if end > len(pcm):
                pcm = np.concatenate([pcm, np.zeros(end - len(pcm), dtype=np.int32)])
            pcm[at:end] += data  # overlapping lines are mixed
            segs.append({"i": i, "voice": voice.split(" ")[0], "text": text,
                         "start": round(at / RATE, 3), "end": round(end / RATE, 3)})
            at = max(0, end + int(pause * RATE))
    pcm = np.clip(pcm, -32768, 32767).astype("<i2").tobytes()
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    seg_path = wav.with_suffix(".segments.json")
    seg_path.write_text(json.dumps({"duration": round(len(pcm) / 2 / RATE, 3), "segments": segs},
                                   ensure_ascii=False, indent=1))
    print(f"{wav}: {len(pcm) / 2 / RATE:.1f} s, {len(segs)} lines; segments in {seg_path}")
    return seg_path


def run(wav: Path, env_file: str, save_dir: Path, tail: float) -> int:
    py = ROOT / ".venv/bin/python"
    devs = json.loads(subprocess.run([str(py), "-m", "kana", "--list-devices", "--json"], check=True,
                                     capture_output=True, text=True).stdout)
    if not any(d["name"] == "BlackHole 2ch" for d in devs["outputs"]):
        sys.exit("BlackHole 2ch is not an output device here; refusing to run (nothing may reach the speakers)")
    with wave.open(str(wav), "rb") as w:
        duration = w.getnframes() / w.getframerate()
    save_dir.mkdir(parents=True, exist_ok=True)
    out = save_dir / "engine.jsonl"
    cmd = [str(py), "-m", "kana", "--only", "in", "--in-file", str(wav), "--spk", "BlackHole 2ch", "--json",
           "--env-file", env_file, "--save-dir", str(save_dir)]
    with open(out, "w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=f, text=True, cwd=ROOT)
        try:
            time.sleep(duration + tail)
            p.stdin.write('{"cmd":"quit"}\n')
            p.stdin.close()
            code = p.wait(timeout=30)
        except BaseException:
            p.terminate()  # only our own child
            raise
    print(f"engine exited {code}; stdout in {out}")
    return code


# --- analysis -------------------------------------------------------------------


def analyze(events_path: Path, segments: Path | None) -> dict:
    from kana.replay import load
    ev = [e for e in load(events_path) if e.get("dir") in (None, "in")]
    t_conn = next(e["t"] for e in ev if e["ev"] == "connected")
    rel = lambda t: round(t - t_conn, 2)  # noqa: E731
    segs = json.loads(segments.read_text())["segments"] if segments else []

    ins = [e for e in ev if e["ev"] == "input_transcription"]
    outs = [e for e in ev if e["ev"] == "output_transcription"]
    turns = [e for e in ev if e["ev"] == "turn_complete"]
    intr = [e for e in ev if e["ev"] == "interrupted"]
    gens = [e for e in ev if e["ev"] == "generation_complete"]

    print(f"connected at t0; {len(ins)} input chunks, {len(outs)} output chunks, {len(turns)} turn_complete, "
          f"{len(gens)} generation_complete, {len(intr)} interrupted")
    print("\n# timeline (s after connect)")
    for e in ev:
        if e["ev"] in ("input_transcription", "output_transcription", "turn_complete", "generation_complete",
                       "interrupted", "stream_end", "utterance_open", "utterance_close", "transcript"):
            extra = e.get("text", "")
            if e["ev"] == "transcript":
                extra = f'{e["kind"]} row {e["row"]}' + (f' merge_into {e["merge_into"]}' if "merge_into" in e else "")
            print(f'{rel(e["t"]):8.2f}  {e["ev"]:<22} {extra}')

    # Chunk interleaving: in arrival order, "i" = input chunk, "o" = output chunk.
    seq = [("i" if e["ev"] == "input_transcription" else "o", e) for e in ev
           if e["ev"] in ("input_transcription", "output_transcription")]
    leads = []  # input chunk -> next output chunk, when no other input comes in between
    runs = {"i": [], "o": []}
    k = 0
    while k < len(seq):
        j = k
        while j < len(seq) and seq[j][0] == seq[k][0]:
            j += 1
        runs[seq[k][0]].append(j - k)
        k = j
    for a, b in zip(seq, seq[1:]):
        if a[0] == "i" and b[0] == "o":
            leads.append(b[1]["t"] - a[1]["t"])

    def sentences(chunks):
        """(first chunk time, last chunk time, chars) per sentence, cut at . ? ! 。 ？ ！"""
        out, first, n = [], None, 0
        for e in chunks:
            first = e["t"] if first is None else first
            n += len(e.get("text", "").strip())
            if e.get("text", "").rstrip().endswith(tuple(".?!。？！")):
                out.append((first, e["t"], n))
                first, n = None, 0
        if first is not None:
            out.append((first, chunks[-1]["t"], n))
        return out

    ja, en = sentences(ins), sentences(outs)
    hold_ja = sorted(b - a for a, b, _ in ja)
    hold_en = sorted(b - a for a, b, _ in en)
    gaps_in = sorted(b["t"] - a["t"] for a, b in zip(ins, ins[1:]))

    def dist(xs):
        if not xs:
            return None
        return {"n": len(xs), "median": round(statistics.median(xs), 2),
                "p90": round(xs[min(len(xs) - 1, int(len(xs) * 0.9))], 2), "max": round(max(xs), 2)}

    print("\n# input sentences (as the sentence buffer flushes them): first chunk -> sentence end")
    for a, b, n in ja:
        print(f"  {rel(a):7.2f} -> {rel(b):7.2f}  held {b - a:5.1f} s  {n} chars")

    if segs:
        print("\n# script lines: start-end in the WAV (s after connect) -> first output after start / next input after end")
        for s_ in segs:
            nxt_in = next((rel(e["t"]) for e in ins if rel(e["t"]) >= s_["end"]), None)
            nxt_out = next((rel(o["t"]) for o in outs if rel(o["t"]) >= s_["start"]), None)
            print(f'line {s_["i"]:2d} {s_["voice"]:<5} {s_["start"]:6.2f}-{s_["end"]:6.2f}  '
                  f'first out after start {nxt_out}  next in after end {nxt_in}')

    summary = {"inputs": len(ins), "outputs": len(outs), "turn_complete": len(turns),
               "interrupted": len(intr), "generation_complete": len(gens),
               "finished_flags": sum(1 for e in ins + outs if e.get("fin")),
               "input_gap_s": dist(gaps_in),
               "input_to_next_output_s": dist(sorted(leads)),
               "input_runs": {n: runs["i"].count(n) for n in sorted(set(runs["i"]))},
               "output_runs": {n: runs["o"].count(n) for n in sorted(set(runs["o"]))},
               "input_sentence_hold_s": dist(hold_ja),
               "output_sentence_hold_s": dist(hold_en),
               "input_sentences": len(ja), "output_sentences": len(en)}
    print("\n# summary")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("synth")
    a.add_argument("wav", type=Path)
    a.add_argument("--script", choices=sorted(SCRIPTS), default="clean")
    b = sub.add_parser("run")
    b.add_argument("wav", type=Path)
    b.add_argument("--env-file", required=True)
    b.add_argument("--save-dir", type=Path, required=True)
    b.add_argument("--tail", type=float, default=30.0, help="seconds to keep running after the WAV (late transcripts)")
    c = sub.add_parser("analyze")
    c.add_argument("events", type=Path)
    c.add_argument("--segments", type=Path)
    args = p.parse_args(argv)
    if args.cmd == "synth":
        synth(args.wav, args.script)
    elif args.cmd == "run":
        return run(args.wav, args.env_file, args.save_dir, args.tail)
    else:
        analyze(args.events, args.segments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
