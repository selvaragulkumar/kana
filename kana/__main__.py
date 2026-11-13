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

from . import audio, backend, events, paths
from .openai_session import OPENAI_MODEL, OpenAIDirection
from .ptt import PTT
from .session import AUDIO_RATES_PER_MIN, DEFAULT_MODEL, FALLBACK_MODEL, KEIGO_INSTRUCTION, Direction
from .transcripts import TranscriptWriter
from .vad import DEFAULT_HANGOVER_MS, VAD

ROOT = Path(__file__).resolve().parent.parent
MEET_MIC, MEET_SPK = audio.meeting_cables()  # BlackHole 2ch/16ch on macOS, CABLE-A/CABLE-B on Windows


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="kana",
                                description="Two-way live voice translation for meetings (Gemini Live).")
    p.add_argument("--mic", help="your real microphone (substring; default: system default input)")
    p.add_argument("--spk", help="your earphones (substring; default: system default output)")
    p.add_argument("--meet-mic", default=MEET_MIC, help="device Meet uses as Microphone (default: %(default)s)")
    p.add_argument("--meet-spk", default=MEET_SPK, help="device Meet uses as Speakers (default: %(default)s)")
    p.add_argument("--in", dest="in_lang", default="en", help="language you hear (BCP-47, default: %(default)s)")
    p.add_argument("--out", dest="out_lang", default="ja", help="language Meet hears (BCP-47, default: %(default)s)")
    p.add_argument("--provider", choices=["gemini", "openai"],
                   help="translation engine: gemini = Gemini Live Translate, your own voice (default); "
                        f"openai = OpenAI {OPENAI_MODEL}, needs OPENAI_API_KEY (docs/ENGINE.md)")
    p.add_argument("--model", help=f"model (default: {DEFAULT_MODEL}; fallback: gemini-3.8-live; "
                                   f"{OPENAI_MODEL} implies --provider openai)")
    p.add_argument("--env-file", help="also read API keys from this .env file")
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
    p.add_argument("--host-api", default="auto",
                   help="audio host API whose devices are used (substring of a PortAudio host API name): "
                        "auto = Windows WASAPI on Windows, every host API elsewhere; all = no filter "
                        "(default: %(default)s; docs/research/windows.md)")
    p.add_argument("--vad", choices=["auto", "off"], default="auto",
                   help="voice-activity gating of what is sent: auto = silence is not streamed (default: %(default)s)")
    p.add_argument("--vad-threshold", type=float, default=200.0,
                   help="absolute speech level, int16 RMS of a 100 ms chunk (default: %(default)s)")
    p.add_argument("--vad-hangover", type=int, default=DEFAULT_HANGOVER_MS,
                   help="ms of audio still sent after speech ends, before the stream end (default: %(default)s)")
    p.add_argument("--catch-up", choices=["on", "off"], default="on",
                   help="drop the model's streamed silence while playback is behind, so its next words are not "
                        "queued behind it (default: %(default)s; docs/LATENCY.md)")
    p.add_argument("--capture-latency", choices=["low", "default"], default="low",
                   help="BlackHole capture: low = PortAudio latency low with 10 ms blocks, so each 100 ms chunk "
                        "reaches the engine ~60 ms sooner; other inputs keep the defaults "
                        "(default: %(default)s; docs/LATENCY.md)")
    p.add_argument("--backend", choices=backend.BACKENDS, default="developer",
                   help="where the Live sessions run: developer = Gemini Developer API with GEMINI_API_KEY; "
                        "vertex = Vertex AI at location global with gcloud application-default credentials "
                        "(default: %(default)s; docs/LATENCY.md)")
    p.add_argument("--gcp-project", help="Google Cloud project for --backend vertex "
                                         "(default: GOOGLE_CLOUD_PROJECT, then `gcloud config get-value project`)")
    p.add_argument("--save-dir",
                   help="transcripts go to <dir>/transcripts/YYYY-MM-DD-HHMM.md/.srt "
                        f"(default: {paths.SUPPORT_DIR_HELP})")
    p.add_argument("--no-save", action="store_true", help="do not save transcripts")
    p.add_argument("--passthrough", action="store_true",
                   help="no translation, no network, no key: copy the meeting (--meet-spk) to your earphones "
                        "(--spk) and your microphone (--mic) to the meeting (--meet-mic) untranslated. The "
                        "microphone is NOT gated by talk; mute in the meeting app (docs/ENGINE.md)")
    p.add_argument("--json", action="store_true",
                   help="JSON lines on stdout, commands on stdin (protocol for the menu-bar app)")
    return resolve_platform(resolve_provider(p.parse_args(argv)))


def resolve_platform(args, platform=None):
    """Fills args.save_dir (paths.support_dir()) and args.host_api: "auto" becomes
    WASAPI on Windows and None (no filter) elsewhere, "all" becomes None."""
    if args.save_dir is None:
        args.save_dir = str(paths.support_dir(platform))
    if args.host_api == "auto":
        args.host_api = audio.default_host_api(platform)
    elif args.host_api.lower() == "all":
        args.host_api = None
    return args


def resolve_device(args, name, kind):
    """(index, name) of a device; the host API filter is passed only when one is set."""
    host = {"host_api": args.host_api} if getattr(args, "host_api", None) else {}
    i = audio.find_device(name, kind, **host)
    return i, audio.device_name(i, kind)


def resolve_provider(args):
    """Fills args.provider and args.model. `--model gpt-...` implies openai, and
    `--provider openai` alone picks gpt-realtime-translate. A contradiction is kept in
    args.provider_error and reported by main() as a fatal error (JSON mode needs an event)."""
    args.provider_error = None
    model_says = None if args.model is None else ("openai" if args.model.startswith("gpt-") else "gemini")
    if args.provider and model_says and args.provider != model_says:
        args.provider_error = f"--model {args.model} is not a {args.provider} model"
    args.provider = args.provider or model_says or "gemini"
    if args.model is None:
        args.model = OPENAI_MODEL if args.provider == "openai" else DEFAULT_MODEL
    if args.provider == "openai" and args.register == "business" and not args.provider_error:
        args.provider_error = (f"--register business is not available with {OPENAI_MODEL}: it takes no "
                               "instruction, so keigo cannot be asked for. Use --provider gemini.")
    return args


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
        return resolve_device(args, name, kind)

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


def devices_json(devices, hostapi: int | None = None) -> dict:
    """{"inputs":[{"index","name"}], "outputs":[...]} from sd.query_devices(). With
    `hostapi` (an index) only that host API's devices are listed: Windows lists each
    endpoint once per host API."""
    return {kind + "s": [{"index": i, "name": d["name"]} for i, d in enumerate(devices)
                         if d[f"max_{kind}_channels"] > 0 and (hostapi is None or d.get("hostapi") == hostapi)]
            for kind in ("input", "output")}


def direction_models(args) -> dict:
    """{"IN"|"OUT": (model, instruction)}. Live Translate takes no reliable
    instruction and mirrors the speaker's register (docs/REGISTER.md), so business
    register moves the outbound Japanese direction to the general Live model with
    a keigo instruction. Inbound always stays on --model."""
    out = (args.model, None)
    if (getattr(args, "provider", "gemini") == "gemini" and args.register == "business"
            and args.out_lang.split("-")[0].lower() == "ja"):
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
    be = getattr(args, "backend", "developer")
    return {"in": side("IN"), "out": side("OUT"), "model": args.model, "register": args.register,
            "in_model": backend.model_label(models["IN"][0], be) if "IN" in dirs else None,
            "out_model": backend.model_label(models["OUT"][0], be) if "OUT" in dirs else None,
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

    def save(direction, row):  # one row per paired source/translation (kana/pairing.py)
        writer.add(direction, row.src_text, row.dst_text, row.first, row.last)
    tasks = []
    directions = {}
    with contextlib.ExitStack() as stack:
        for label, ((kind, *src), (sink_i, _)) in dirs.items():
            in_q, out_q = asyncio.Queue(maxsize=50), asyncio.Queue()
            if kind == "file":
                pcm = audio.read_wav_16k(src[0])
            else:
                stack.enter_context(audio.Capture(src[0], in_q, loop,
                                                  **audio.capture_options(src[1], args.capture_latency)))
            catch_up = audio.CATCH_UP_MS if args.catch_up == "on" else None
            player = stack.enter_context(audio.Playback(sink_i, catch_up_ms=catch_up))
            tasks.append(asyncio.create_task(player.pump(out_q)))
            model, instruction = direction_models(args)[label]
            cls = OpenAIDirection if getattr(args, "provider", "gemini") == "openai" else Direction
            d = cls(label, *langs[label], model, in_q, out_q, connect=connect, instruction=instruction,
                          is_muted=(lambda: ptt.muted) if label == "OUT" else (lambda: False),
                          dump=dumps[label], emit=emit,
                          vad=VAD(gate=args.vad == "auto", threshold=args.vad_threshold, hangover_ms=args.vad_hangover),
                          on_row=save if writer else None)
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


def plan_passthrough(args) -> dict:
    """{"IN": ((i, name) meeting capture, (i, name) earphones),
        "OUT": ((i, name) microphone, (i, name) meeting microphone)}, loop-checked."""
    def dev(name, kind):
        return resolve_device(args, name, kind)
    routes = {"IN": (dev(args.meet_spk, "input"), dev(args.spk, "output")),
              "OUT": (dev(args.mic, "input"), dev(args.meet_mic, "output"))}
    audio.check_passthrough(routes)
    return routes


def passthrough_ready_fields(routes) -> dict:
    return {"mode": "passthrough",
            **{label.lower(): {"src": src[1], "sink": sink[1]} for label, (src, sink) in routes.items()}}


async def run_passthrough(routes, emit=None, commands=None, make=None) -> None:
    """Pass-through: one audio.Passthrough per route until quit, EOF (JSON mode)
    or Ctrl-C (terminal). `make` replaces audio.Passthrough in tests."""
    make = make or audio.Passthrough
    with contextlib.ExitStack() as stack:
        for (src_i, _), (sink_i, _) in routes.values():
            stack.enter_context(make(src_i, sink_i))
        if emit is None:
            for label, (src, sink) in routes.items():
                print(f"  {label:<3} {src[1]} -> {sink[1]}")
            print("  pass-through: no translation, the microphone is live to the meeting. Ctrl-C quits.")
            await asyncio.Event().wait()
        else:
            emit("ready", **passthrough_ready_fields(routes))
            await events.passthrough_command_loop(
                commands if commands is not None else events.stdin_lines(), emit)


def main_passthrough(args, emit, fatal) -> int:
    try:
        routes = plan_passthrough(args)
    except audio.DeviceError as e:
        return fatal(str(e))
    if emit is None:
        print("kana pass-through")
    try:
        asyncio.run(run_passthrough(routes, emit=emit))
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


def summary(args, dirs) -> None:
    def src(s):
        return f"file {s[1]}" if s[0] == "file" else s[2]
    models = direction_models(args)
    print(f"kana  register={args.register}  in={models['IN'][0]}  out={models['OUT'][0]}  backend={args.backend}")
    if "IN" in dirs:
        print(f"  IN  {args.out_lang}->{args.in_lang}: {src(dirs['IN'][0])} -> {dirs['IN'][1][1]}")
    if "OUT" in dirs:
        print(f"  OUT {args.in_lang}->{args.out_lang}: {src(dirs['OUT'][0])} -> {dirs['OUT'][1][1]}")
    rate = AUDIO_RATES_PER_MIN[OPENAI_MODEL] if args.provider == "openai" else 0.04
    print(f"  cost ~${rate:.3f}/min of audio sent per direction (~${rate * len(dirs):.3f}/min now)")
    print("  keys: space = toggle talk, q = quit (Ctrl-C also quits)")


def main(argv=None) -> int:
    paths.utf8_stdio()  # Windows: the protocol is UTF-8, not the ANSI code page
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
            try:
                ha = None if args.host_api is None else audio.host_api_index(args.host_api, sd.query_hostapis())
            except audio.DeviceError as e:
                return fatal(str(e))
            print(json.dumps(devices_json(sd.query_devices(), ha), ensure_ascii=False))
        else:
            print(sd.query_devices())
        return 0
    if args.passthrough:  # no key, no network: checked before the provider and key
        return main_passthrough(args, emit, fatal)
    if args.provider_error:
        return fatal(args.provider_error)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv()
    if args.env_file:
        load_dotenv(Path(args.env_file).expanduser())
    project = None
    if args.provider == "openai":
        if args.backend == "vertex":
            return fatal("--backend vertex applies to the Gemini provider only.")
        if not os.environ.get("OPENAI_API_KEY"):
            return fatal(f"OPENAI_API_KEY is not set: put OPENAI_API_KEY=... in {ROOT / '.env'} or export it.")
    elif args.backend == "vertex":
        project = backend.gcp_project(args.gcp_project)
        if not project:
            return fatal("--backend vertex needs a Google Cloud project: pass --gcp-project, set "
                         "GOOGLE_CLOUD_PROJECT or run `gcloud config set project ...`.")
    elif not os.environ.get("GEMINI_API_KEY"):
        return fatal(f"GEMINI_API_KEY is not set: put GEMINI_API_KEY=... in {ROOT / '.env'} or export it.")
    try:
        dirs = plan(args)
    except audio.DeviceError as e:
        return fatal(str(e))
    if emit is None:
        summary(args, dirs)
    if args.provider == "openai":
        from .openai_session import make_connect
        connect = make_connect(os.environ["OPENAI_API_KEY"])
    else:
        connect = backend.make_client(args.backend, project).aio.live.connect
    try:
        asyncio.run(amain(args, dirs, connect, emit=emit))
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
