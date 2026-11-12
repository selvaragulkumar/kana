"""python -m kana: two-way live voice translation for meetings."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import wave
from pathlib import Path

from . import audio, events
from .ptt import PTT
from .session import DEFAULT_MODEL, FALLBACK_MODEL, KEIGO_INSTRUCTION, Direction
from .transcripts import TranscriptWriter
from .vad import DEFAULT_HANGOVER_MS, VAD

ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="kana",
                                description="Two-way live voice translation for meetings (Gemini Live).")
    p.add_argument("--mic", help="your real microphone (substring; default: system default input)")
    p.add_argument("--spk", help="your earphones (substring; default: system default output)")
    p.add_argument("--meet-mic", default="BlackHole 2ch", help="device Meet uses as Microphone (default: %(default)s)")
    p.add_argument("--meet-spk", default="BlackHole 16ch", help="device Meet uses as Speakers (default: %(default)s)")
    p.add_argument("--in", dest="in_lang", default="en", help="language you hear (BCP-47, default: %(default)s)")
    p.add_argument("--out", dest="out_lang", default="ja", help="language Meet hears (BCP-47, default: %(default)s)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Live model (default: %(default)s; fallback: gemini-3.8-live)")
    p.add_argument("--register", choices=["default", "business"], default="default",
                   help="outbound Japanese register: default = Live Translate with your own voice, mirroring "
                        "your register; business = keigo guaranteed via the general Live model, stock voice "
                        "(default: %(default)s; see docs/REGISTER.md)")
    p.add_argument("--in-file", help="WAV replacing the Meet capture (inbound source)")
    p.add_argument("--out-file", help="WAV replacing your microphone (outbound source)")
    p.add_argument("--dump-in", help="also write inbound translated audio (24 kHz) to this WAV")
    p.add_argument("--dump-out", help="also write outbound translated audio (24 kHz) to this WAV")
    p.add_argument("--only", choices=["in", "out"], help="run a single direction")
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    p.add_argument("--vad", choices=["auto", "off"], default="auto",
                   help="voice-activity gating of what is sent: auto = silence is not streamed (default: %(default)s)")
    p.add_argument("--vad-threshold", type=float, default=200.0,
                   help="absolute speech level, int16 RMS of a 100 ms chunk (default: %(default)s)")
    p.add_argument("--vad-hangover", type=int, default=DEFAULT_HANGOVER_MS,
                   help="ms of audio still sent after speech ends, before the stream end (default: %(default)s)")
    p.add_argument("--save-dir", default="~/Library/Application Support/kana",
                   help="transcripts go to <dir>/transcripts/YYYY-MM-DD-HHMM.md/.srt (default: %(default)s)")
    p.add_argument("--no-save", action="store_true", help="do not save transcripts")
    p.add_argument("--json", action="store_true",
                   help="JSON lines on stdout, commands on stdin (protocol for the menu-bar app)")
    return p.parse_args(argv)


def open_dump(path):
    if not path:
        return None
    w = wave.open(path, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(audio.OUT_RATE)
    return w


def plan(args):
    """Resolve devices for each enabled direction. Returns {dir: (src, sink)} where
    src is ("file", path) or ("dev", index, name) and sink is (index, name)."""
    def dev(name, kind):
        i = audio.find_device(name, kind)
        return i, audio.device_name(i, kind)

    dirs = {}
    if args.only != "out":
        src = ("file", args.in_file) if args.in_file else ("dev", *dev(args.meet_spk, "input"))
        dirs["IN"] = (src, dev(args.spk, "output"))
    if args.only != "in":
        src = ("file", args.out_file) if args.out_file else ("dev", *dev(args.mic, "input"))
        dirs["OUT"] = (src, dev(args.meet_mic, "output"))
    if len(dirs) == 2:  # anti-goal: the two paths must never share a device
        (si, ki), (so, ko) = dirs["IN"], dirs["OUT"]
        if si[0] == so[0] == "dev" and si[2] == so[2]:
            raise audio.DeviceError(f'Inbound and outbound would both capture "{si[2]}" (feedback loop); pick distinct devices')
        if ki[1] == ko[1]:
            raise audio.DeviceError(f'Earphones and Meet microphone are both "{ki[1]}" (feedback loop); pick distinct devices')
    return dirs


def devices_json(devices) -> dict:
    """{"inputs":[{"index","name"}], "outputs":[...]} from sd.query_devices()."""
    return {kind + "s": [{"index": i, "name": d["name"]} for i, d in enumerate(devices)
                         if d[f"max_{kind}_channels"] > 0]
            for kind in ("input", "output")}


def direction_models(args) -> dict:
    """{"IN"|"OUT": (model, instruction)}. Live Translate takes no reliable
    instruction and mirrors the speaker's register (docs/REGISTER.md), so business
    register moves the outbound Japanese direction to the general Live model with
    a keigo instruction. Inbound always stays on --model."""
    out = (args.model, None)
    if args.register == "business" and args.out_lang.split("-")[0].lower() == "ja":
        out = (FALLBACK_MODEL if "translate" in args.model else args.model, KEIGO_INSTRUCTION)
    return {"IN": (args.model, None), "OUT": out}


async def feed_when_connected(d, pcm: bytes, q: asyncio.Queue) -> None:
    """A WAV source starts once its session is up; audio fed earlier would be
    dropped (a live device simply keeps talking, a file would lose its start)."""
    while d.session is None:
        await asyncio.sleep(0.05)
    await audio.feed_file(pcm, q)


def ready_fields(args, dirs) -> dict:
    def side(label):
        if label not in dirs:
            return None
        (src, (_, sink)) = dirs[label]
        return {"src": f"file {src[1]}" if src[0] == "file" else src[2], "sink": sink}
    models = direction_models(args)
    return {"in": side("IN"), "out": side("OUT"), "model": args.model, "register": args.register,
            "in_model": models["IN"][0] if "IN" in dirs else None,
            "out_model": models["OUT"][0] if "OUT" in dirs else None,
            "in_lang": args.in_lang, "out_lang": args.out_lang}


async def amain(args, dirs, connect, emit=None, commands=None) -> None:
    """emit: JSON-mode emitter (None = plain terminal mode). commands: async
    iterator of stdin command lines for JSON mode (default: real stdin)."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    ptt = PTT(muted=not args.out_file, out=print if emit is None else (lambda *_: None))
    langs = {"IN": (args.out_lang, args.in_lang), "OUT": (args.in_lang, args.out_lang)}
    dumps = {"IN": open_dump(args.dump_in), "OUT": open_dump(args.dump_out)}
    writer = None if args.no_save else TranscriptWriter(Path(args.save_dir).expanduser(),
                                                        title=f"{args.out_lang} ↔ {args.in_lang}")

    def save(direction, u):
        writer.add(direction, " ".join(u.src), " ".join(u.dst), u.first, u.last)
    tasks = []
    directions = {}
    with contextlib.ExitStack() as stack:
        for label, ((kind, *src), (sink_i, _)) in dirs.items():
            in_q, out_q = asyncio.Queue(maxsize=50), asyncio.Queue()
            if kind == "file":
                pcm = audio.read_wav_16k(src[0])
            else:
                stack.enter_context(audio.Capture(src[0], in_q, loop))
            player = stack.enter_context(audio.Playback(sink_i))
            tasks.append(asyncio.create_task(player.pump(out_q)))
            model, instruction = direction_models(args)[label]
            d = Direction(label, *langs[label], model, in_q, out_q, connect=connect, instruction=instruction,
                          is_muted=(lambda: ptt.muted) if label == "OUT" else (lambda: False),
                          dump=dumps[label], emit=emit,
                          vad=VAD(gate=args.vad == "auto", threshold=args.vad_threshold, hangover_ms=args.vad_hangover),
                          on_utterance=save if writer else None)
            directions[label] = d
            tasks.append(asyncio.create_task(d.run()))
            if kind == "file":
                tasks.append(asyncio.create_task(feed_when_connected(d, pcm, in_q)))
        if emit is None:
            if ptt.attach(loop, stop.set):
                stack.callback(ptt.detach)
            if writer:
                print(f"  saving to {writer.md}")
            if "OUT" in dirs:
                print(f"[PTT] outbound {ptt.state()}")
        else:
            emit("ready", **ready_fields(args, dirs))
            if writer:
                emit("saved", md=str(writer.md), srt=str(writer.srt))
            emit("talk", on=not ptt.muted)
            tasks.append(asyncio.create_task(events.audio_ticker(directions, emit)))

            async def commands_then_stop():
                try:
                    await events.command_loop(commands if commands is not None else events.stdin_lines(),
                                              ptt, emit)
                finally:
                    stop.set()
            tasks.append(asyncio.create_task(commands_then_stop()))
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for w in dumps.values():
                if w:
                    w.close()


def summary(args, dirs) -> None:
    def src(s):
        return f"file {s[1]}" if s[0] == "file" else s[2]
    models = direction_models(args)
    print(f"kana  register={args.register}  in={models['IN'][0]}  out={models['OUT'][0]}")
    if "IN" in dirs:
        print(f"  IN  {args.out_lang}->{args.in_lang}: {src(dirs['IN'][0])} -> {dirs['IN'][1][1]}")
    if "OUT" in dirs:
        print(f"  OUT {args.in_lang}->{args.out_lang}: {src(dirs['OUT'][0])} -> {dirs['OUT'][1][1]}")
    print(f"  cost ~$0.04/min per direction (~${0.04 * len(dirs):.2f}/min now)")
    print("  keys: space = toggle talk, q = quit (Ctrl-C also quits)")


def main(argv=None) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # transcripts show at once, even when piped
    args = parse_args(argv)
    emit = events.Emitter() if args.json else None

    def fatal(text: str) -> int:
        print(text, file=sys.stderr)
        if emit is not None:
            emit("error", fatal=True, text=text)
        return 2

    if args.list_devices:
        import sounddevice as sd
        if args.json:
            print(json.dumps(devices_json(sd.query_devices()), ensure_ascii=False))
        else:
            print(sd.query_devices())
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        return fatal(f"GEMINI_API_KEY is not set: put GEMINI_API_KEY=... in {ROOT / '.env'} or export it.")
    try:
        dirs = plan(args)
    except audio.DeviceError as e:
        return fatal(str(e))
    if emit is None:
        summary(args, dirs)
    from google import genai
    client = genai.Client(http_options={"api_version": "v1beta"})
    try:
        asyncio.run(amain(args, dirs, client.aio.live.connect, emit=emit))
    except KeyboardInterrupt:
        pass
    except Exception as e:  # device open failures etc.: report, exit 2
        if emit is None:
            raise
        return fatal(f"{type(e).__name__}: {e}")
    if emit is None:
        print("bye")
    else:
        emit("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
