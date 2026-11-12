"""Live integration test against the Gemini Live API (costs a few cents).
Run: .venv/bin/python -m pytest -m live -s"""
import asyncio
import contextlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from dotenv import load_dotenv

from kana import audio
from kana.session import DEFAULT_MODEL, Direction

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
    pytest.mark.skipif(not (shutil.which("say") and shutil.which("ffmpeg")), reason="needs macOS say and ffmpeg"),
]


async def test_japanese_wav_is_translated_to_english(tmp_path):
    aiff, wav = tmp_path / "ja.aiff", tmp_path / "ja.wav"
    subprocess.run(["say", "-v", "Kyoko", "-o", str(aiff), "こんにちは、今日は天気がいいですね。"], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                    "-sample_fmt", "s16", str(wav)], check=True)

    from google import genai
    client = genai.Client(http_options={"api_version": "v1beta"})
    in_q = asyncio.Queue(maxsize=50)
    d = Direction("IN", "ja", "en", os.environ.get("KANA_MODEL", DEFAULT_MODEL), in_q,
                  connect=client.aio.live.connect)
    tasks = [asyncio.create_task(audio.feed_file(audio.read_wav_16k(str(wav)), in_q)),
             asyncio.create_task(d.run())]
    try:
        loop = asyncio.get_running_loop()
        end = loop.time() + 20
        words = ("weather", "hello", "nice")
        while loop.time() < end and not (d.audio_bytes and any(w in d.transcript("out").lower() for w in words)):
            await asyncio.sleep(0.2)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
    out = d.transcript("out").lower()
    assert d.audio_bytes > 0, "no audio received"
    assert any(w in out for w in words), f"unexpected translation: {out!r}"
