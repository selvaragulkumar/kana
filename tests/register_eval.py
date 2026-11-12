"""Register evaluation: how formal is the outbound Japanese? (docs/REGISTER.md)

Synthesises English utterances with macOS `say`, runs each through one
outbound Direction (en -> ja) per configuration against the real Gemini Live
API, and writes the Japanese transcripts to <out>/results.json and a Markdown
table for grading. Costs a few cents.

    .venv/bin/python tests/register_eval.py --out <dir> [--configs translate,translate+instr,fallback+keigo]
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kana import audio  # noqa: E402
from kana.session import DEFAULT_MODEL, FALLBACK_MODEL, KEIGO_INSTRUCTION, Direction  # noqa: E402

UTTERANCES = [
    ("casual", "Hey, can you send me that file?"),
    ("casual", "Yeah that works for me."),
    ("casual", "No way, that's way too expensive."),
    ("casual", "Gimme a sec, I'll check."),
    ("neutral", "We can deliver in three weeks."),
    ("neutral", "What is your budget for this quarter?"),
    ("neutral", "I think the second option is better."),
    ("neutral", "Let's schedule a follow-up next Tuesday."),
    ("polite", "Could you please share the proposal by Friday?"),
    ("polite", "Thank you very much for your time today."),
    ("polite", "I'm afraid we cannot accept those terms."),
    ("polite", "Would it be possible to extend the deadline?"),
]

CONFIGS = {
    "translate": (DEFAULT_MODEL, None),                    # what users get today
    "translate+instr": (DEFAULT_MODEL, KEIGO_INSTRUCTION),  # does Live Translate take an instruction?
    "fallback+keigo": (FALLBACK_MODEL, KEIGO_INSTRUCTION),  # general Live model told to use keigo
}

# Preliminary marks only; the grade in docs/REGISTER.md is a human reading.
KEIGO = re.compile(r"いただ|ございま|おります|申し|存じ|いたし|させていただ|恐れ入|恐縮|伺|頂|くださいませ|お願い申し")
POLITE = re.compile(r"(です|ます|ません|でした|ました|ましょう|ください|ませんか|でしょうか)[。？！?!、]?\s*$|"
                    r"(です|ます|ません|でした|ました|ましょう|ください|でしょう)[。？！?!]")


def pre_grade(ja: str) -> str:
    if not ja.strip():
        return "none"
    sentences = [s for s in re.split(r"(?<=[。？！?!])", ja) if s.strip()]
    if not all(POLITE.search(s) for s in sentences):
        return "casual?"
    return "keigo?" if KEIGO.search(ja) else "polite?"


def synth(text: str, folder: Path, i: int) -> Path:
    aiff, wav = folder / f"u{i:02d}.aiff", folder / f"u{i:02d}.wav"
    if not wav.exists():
        subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), text], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                        "-sample_fmt", "s16", str(wav)], check=True)
    return wav


async def run_one(client, model: str, instruction: str | None, wav: Path, settle_s=3.0, cap_s=25.0) -> dict:
    logs: list[str] = []
    in_q: asyncio.Queue = asyncio.Queue(maxsize=50)
    d = Direction("OUT", "en", "ja", model, in_q, connect=client.aio.live.connect, out=logs.append,
                  instruction=instruction)
    pcm = audio.read_wav_16k(str(wav))
    speech_s = len(pcm) / 32000
    tasks = [asyncio.create_task(d.run())]
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    while d.session is None and loop.time() - t0 < 10:  # audio fed before connect would be dropped
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.3)
    tasks.append(asyncio.create_task(audio.feed_file(bytes(3200 * 5) + pcm, in_q)))  # 0.5 s lead-in
    start = loop.time()
    last_text, changed = "", start
    try:
        while loop.time() - start < cap_s:
            await asyncio.sleep(0.2)
            text = d.transcript("out")
            if text != last_text:
                last_text, changed = text, loop.time()
            done_speaking = loop.time() - start > speech_s + 1.0
            if done_speaking and text and loop.time() - changed > settle_s:
                break
            if any("error" in l for l in logs) and d.connects == 0 and loop.time() - start > 6:
                break  # the server keeps refusing the config
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
    return {"ja": d.transcript("out").strip(), "heard": d.transcript("in").strip(),
            "audio_s": round(d.audio_bytes / 48000, 1), "connects": d.connects,
            "onset_to_audio_ms": d.latencies[0] if d.latencies else None,
            "errors": [l for l in logs if "error" in l][:3]}


async def main_async(args) -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        return 2
    from google import genai
    client = genai.Client(http_options={"api_version": "v1beta"})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wavs = [synth(text, out, i) for i, (_, text) in enumerate(UTTERANCES)]
    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async def job(cfg: str, i: int):
        model, instruction = CONFIGS[cfg]
        async with sem:
            r = await run_one(client, model, instruction, wavs[i])
        r.update(config=cfg, model=model, i=i, register=UTTERANCES[i][0], en=UTTERANCES[i][1],
                 pre_grade=pre_grade(r["ja"]))
        results.append(r)
        print(f"[{cfg}] {i:2d} {r['pre_grade']:8s} {r['en']} => {r['ja']}"
              + (f"  ERR {r['errors'][0]}" if r["errors"] else ""), flush=True)

    await asyncio.gather(*(job(c, i) for c in args.configs.split(",") for i in range(len(UTTERANCES))))
    results.sort(key=lambda r: (r["config"], r["i"]))
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    rows = ["| # | Input register | English | Config | Japanese | Pre-grade |", "|---|---|---|---|---|---|"]
    rows += [f"| {r['i'] + 1} | {r['register']} | {r['en']} | {r['config']} | {r['ja'] or '(none)'} | {r['pre_grade']} |"
             for r in results]
    (out / "table.md").write_text("\n".join(rows) + "\n")
    print(f"wrote {out / 'results.json'} and {out / 'table.md'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", required=True, help="folder for audio and results")
    p.add_argument("--configs", default=",".join(CONFIGS), help="comma list of: " + ", ".join(CONFIGS))
    p.add_argument("--concurrency", type=int, default=6)
    return asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
