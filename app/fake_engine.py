#!/usr/bin/env python3
"""Fake kana engine for testing the app without audio or an API key.

Speaks the engine's --json protocol (docs/superpowers/specs/2026-11-12-menubar-app-design.md):
  fake_engine.py --list-devices --json   -> one device-list line, exit 0
  fake_engine.py --json [--in en --out ja ...]
      -> ready, talk, session, audio ticks every second, inbound transcripts every few seconds,
         outbound transcripts while talk is on; one reconnect and one non-fatal error along the way.
         Honours {"cmd":"talk","on":bool} and {"cmd":"quit"} on stdin.
         Also reports register and in_model/out_model in ready (model "fake"), emits usage events,
         per-utterance latency events, gated_s/latency_ms on the audio tick, one outbound
         row in four that gets no translation (an untranslated event), and a
         saved event; the Markdown/SRT files are written to <tmp>/kana-fake/transcripts
         (or --save-dir) unless --no-save is given.
  --provider openai: usage is priced per minute of audio sent and marked est (no token counts),
         as the real engine does for gpt-realtime-translate; --register business is then fatal.
  fake_engine.py --json --passthrough [--mic X --spk Y]
      -> ready with "mode": "passthrough", then nothing until {"cmd":"quit"} or EOF, then bye.
         A --spk naming a BlackHole device is a fatal error, as in the real engine.
  FAKE_ENGINE_FATAL=1 makes it exit with a fatal error after ~6 s.
Stdlib only.
"""
import json
import os
import statistics
import sys
import tempfile
import threading
import time

lock = threading.Lock()
state = {"talk": False, "quit": False}


def emit(ev, **fields):
    with lock:
        sys.stdout.write(json.dumps({"t": time.time(), "ev": ev, **fields}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def arg(name, default):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def stdin_loop():
    for line in sys.stdin:
        try:
            cmd = json.loads(line)
        except ValueError:
            emit("error", fatal=False, text=f"bad command: {line.strip()!r}")
            continue
        if cmd.get("cmd") == "talk":
            state["talk"] = bool(cmd.get("on"))
            emit("talk", on=state["talk"])
        elif cmd.get("cmd") == "quit":
            state["quit"] = True
            return
    state["quit"] = True  # stdin closed: parent went away


INBOUND = [
    ("こんにちは、聞こえますか？", "Hello, can you hear me?"),
    ("今日はお時間をいただきありがとうございます。", "Thank you for your time today."),
    ("では、見積もりの件から始めましょう。", "Let's start with the quotation."),
    ("来週の火曜日はいかがでしょうか。", "How about next Tuesday?"),
    ("資料は後ほどメールでお送りします。", "I'll send the materials by email later."),
]
OUTBOUND = [
    ("Yes, I can hear you clearly.", "はい、よく聞こえます。"),
    ("Tuesday works for me.", "火曜日で大丈夫です。"),
    ("Could you share the slides?", "スライドを共有していただけますか？"),
    ("はい、そうですね。", None),  # the other person's voice in the mic: no translation (untranslated)
]


def main():
    if "--list-devices" in sys.argv:
        emit_devices()
        return 0

    if "--passthrough" in sys.argv:
        return passthrough()

    in_lang, out_lang = arg("--in", "en"), arg("--out", "ja")
    only = arg("--only", None)
    openai = arg("--provider", "gemini") == "openai"
    if openai and arg("--register", "default") == "business":
        text = "--register business is not available with gpt-realtime-translate. Use --provider gemini."
        print(text, file=sys.stderr)
        emit("error", fatal=True, text=text)
        return 2
    threading.Thread(target=stdin_loop, daemon=True).start()
    time.sleep(0.5)
    emit("ready",
         **{"in": {"src": "Fake Meet capture", "sink": arg("--spk", "Fake Speaker 1")},
            "out": {"src": arg("--mic", "Fake Mic 1"), "sink": "Fake Meet mic"}},
         model="fake", register=arg("--register", "default"),
         in_model="fake" if only in (None, "in") else None,
         out_model="fake" if only in (None, "out") else None,
         in_lang=in_lang, out_lang=out_lang)
    md = srt = None
    if "--no-save" not in sys.argv:
        base = os.path.expanduser(arg("--save-dir", os.path.join(tempfile.gettempdir(), "kana-fake")))
        folder = os.path.join(base, "transcripts")
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H%M")
        md, srt = os.path.join(folder, f"{stamp}.md"), os.path.join(folder, f"{stamp}.srt")
        with open(md, "w") as f:
            f.write(f"# kana (fake engine) {stamp}\n\n| | Heard | Translation |\n|---|---|---|\n")
        open(srt, "w").close()
        emit("saved", md=md, srt=srt)
    emit("talk", on=False)
    emit("session", dir="in", state="connected", detail="")
    emit("session", dir="out", state="connected", detail="")

    sent = {"in": 0.0, "out": 0.0}
    recv = {"in": 0.0, "out": 0.0}
    gated = {"in": 0.0, "out": 0.0}
    last_usage = {"in": (0, 0), "out": (0, 0)}
    lat = {"in": [], "out": []}
    srt_n = [0]

    rows = {"in": 0, "out": 0}

    def utterance(d, src, dst, onset_ms):
        rows[d] += 1  # the real engine pairs by timing and names the row (kana/pairing.py)
        emit("transcript", dir=d, kind="src", text=src, row=rows[d], row_text=src, final=True)
        time.sleep(0.4)
        if dst is None:  # the model said nothing (speech already in the target language)
            emit("untranslated", dir=d, row=rows[d])
            emit("latency", dir=d, onset_to_audio_ms=None, src_final_to_dst_final_ms=None)
            return
        emit("transcript", dir=d, kind="dst", text=dst, row=rows[d], row_text=dst, final=True)
        lat[d].append(onset_ms)
        emit("latency", dir=d, onset_to_audio_ms=onset_ms, src_final_to_dst_final_ms=400 + onset_ms // 6)
        recv[d] += 2.0
        if md:
            with open(md, "a") as f:
                f.write(f"| {'↓' if d == 'in' else '↑'} | {src} | {dst} |\n")
            srt_n[0] += 1
            with open(srt, "a") as f:
                f.write(f"{srt_n[0]}\n00:00:{srt_n[0]:02d},000 --> 00:00:{srt_n[0] + 1:02d},000\n{dst}\n\n")
    tick, i_in, i_out = 0, 0, 0
    fatal_at = 6 if os.environ.get("FAKE_ENGINE_FATAL") else None
    while not state["quit"]:
        time.sleep(1)
        tick += 1
        # Voice-activity gating: speech ticks are sent, silent ones are skipped.
        if tick % 4 in (0, 3):
            sent["in"] += 1.0
        else:
            gated["in"] += 1.0
        if state["talk"]:
            sent["out"] += 1.0
        else:
            gated["out"] += 1.0
        if tick % 4 == 0:
            src, dst = INBOUND[i_in % len(INBOUND)]
            i_in += 1
            utterance("in", src, dst, 1600 + 150 * (i_in % 4))
        if state["talk"] and tick % 3 == 0:
            src, dst = OUTBOUND[i_out % len(OUTBOUND)]
            i_out += 1
            utterance("out", src, dst, 1900 + 200 * (i_out % 3))
        for d in ("in", "out"):
            med = statistics.median(lat[d]) if lat[d] else None
            in_tok, out_tok = int(sent[d] * 25), int(recv[d] * 25)  # 25 tokens per audio second
            usd = round(in_tok * 3.5e-6 + out_tok * 21e-6, 5)
            if openai:  # $0.034 per minute sent, no server counts
                usd = round(sent[d] / 60 * 0.034, 6)
                if sent[d] and (sent[d], 0) != last_usage[d]:
                    last_usage[d] = (sent[d], 0)
                    emit("usage", dir=d, model="fake", sent_s=round(sent[d], 1), usd=usd, est=True)
                emit("audio", dir=d, sent_s=round(sent[d], 1), recv_s=round(recv[d], 1),
                     gated_s=round(gated[d], 1), latency_ms=med, usd=usd, est=True)
                continue
            if (in_tok, out_tok) != last_usage[d]:
                last_usage[d] = (in_tok, out_tok)
                emit("usage", dir=d, model="fake", in_audio_tokens=in_tok, out_audio_tokens=out_tok,
                     usd=usd, in_text_tokens=0)
            emit("audio", dir=d, sent_s=round(sent[d], 1), recv_s=round(recv[d], 1),
                 gated_s=round(gated[d], 1), latency_ms=med, usd=usd)
        if tick == 10:
            emit("session", dir="in", state="reconnecting", detail="go_away")
        if tick == 11:
            emit("session", dir="in", state="connected", detail="")
        if tick == 14:
            emit("error", fatal=False, text="fake: dropped one audio chunk")
        if fatal_at and tick == fatal_at:
            emit("error", fatal=True, text="fake: fatal error requested by FAKE_ENGINE_FATAL")
            return 2

    emit("session", dir="in", state="closed", detail="")
    emit("session", dir="out", state="closed", detail="")
    emit("bye")
    return 0


def passthrough():
    """--passthrough: ready with mode, then nothing until quit or EOF (no talk, no transcripts)."""
    if "blackhole" in arg("--spk", "").lower():
        text = f'Earphones are "{arg("--spk", "")}", a BlackHole device: pick your real earphones.'
        print(text, file=sys.stderr)
        emit("error", fatal=True, text=text)
        return 2
    threading.Thread(target=stdin_loop, daemon=True).start()
    time.sleep(0.3)
    emit("ready", mode="passthrough",
         **{"in": {"src": "Fake Meet capture", "sink": arg("--spk", "Fake Speaker 1")},
            "out": {"src": arg("--mic", "Fake Mic 1"), "sink": "Fake Meet mic"}})
    while not state["quit"]:
        time.sleep(0.1)
    emit("bye")
    return 0


def emit_devices():
    # Unmistakably fake names, so a test panel never looks like it shows real hardware.
    emit_raw = {
        "fake": True,
        "inputs": [
            {"index": 0, "name": "Fake Mic 1"},
            {"index": 1, "name": "Fake Mic 2"},
        ],
        "outputs": [
            {"index": 2, "name": "Fake Speaker 1"},
            {"index": 3, "name": "Fake Speaker 2"},
        ],
    }
    sys.stdout.write(json.dumps(emit_raw) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
