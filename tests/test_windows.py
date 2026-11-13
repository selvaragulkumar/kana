"""Windows groundwork (docs/research/windows.md): paths, device names, host API,
console keys. Everything runs on macOS with fake device tables; nothing here
proves the Windows behaviour, only that the engine's rules are as designed and
that macOS is unchanged."""
import asyncio
import io
import sys
from pathlib import Path

import pytest

from kana import __main__ as cli
from kana import audio, paths, transcripts
from kana.ptt import PTT

HOME = Path("/home/u")

# What PortAudio lists on Windows with VB-CABLE A+B: each endpoint once per host API.
# MME (index 0) cuts names to 31 characters.
HOSTAPIS = [
    {"name": "MME", "default_input_device": 1, "default_output_device": 4},
    {"name": "Windows WASAPI", "default_input_device": 6, "default_output_device": 9},
]
WIN_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Microphone (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "CABLE-A Output (VB-Audio Cable ", "hostapi": 0, "max_input_channels": 8, "max_output_channels": 0},
    {"name": "CABLE-B Output (VB-Audio Cable ", "hostapi": 0, "max_input_channels": 8, "max_output_channels": 0},
    {"name": "Speakers (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "CABLE-A Input (VB-Audio Cable A", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 8},
    {"name": "Microphone (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "CABLE-A Output (VB-Audio Cable A)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "CABLE-B Output (VB-Audio Cable B)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Headphones (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "CABLE-A Input (VB-Audio Cable A)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "CABLE-B Input (VB-Audio Cable B)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
]


def find(name, kind, host_api="wasapi"):
    return audio.find_device(name, kind, WIN_DEVICES, host_api=host_api, hostapis=HOSTAPIS)


# --- paths ---

def test_support_dir_per_platform():
    assert paths.support_dir("darwin", {}, HOME) == HOME / "Library" / "Application Support" / "kana"
    assert paths.support_dir("win32", {"LOCALAPPDATA": "C:/Users/u/AppData/Local"}, HOME) == \
        Path("C:/Users/u/AppData/Local") / "kana"
    assert paths.support_dir("win32", {}, HOME) == HOME / "AppData" / "Local" / "kana"
    assert paths.support_dir("linux", {"XDG_DATA_HOME": "/x"}, HOME) == Path("/x/kana")
    assert paths.support_dir("linux", {}, HOME) == HOME / ".local" / "share" / "kana"


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS default")
def test_macos_defaults_are_unchanged():
    old = Path("~/Library/Application Support/kana").expanduser()
    assert transcripts.default_dir() == old
    a = cli.parse_args([])
    assert Path(a.save_dir).expanduser() == old
    assert (a.meet_mic, a.meet_spk, a.host_api) == ("BlackHole 2ch", "BlackHole 16ch", None)


def test_resolve_platform_on_windows():
    a = cli.parse_args(["--save-dir", "/tmp/x"])
    a.host_api = "auto"
    assert cli.resolve_platform(a, "win32").host_api == "wasapi"
    assert a.save_dir == "/tmp/x"  # an explicit --save-dir wins
    a.host_api, a.save_dir = "all", None
    cli.resolve_platform(a, "win32")
    assert a.host_api is None and a.save_dir.endswith("kana")
    assert cli.parse_args(["--host-api", "mme"]).host_api == "mme"


def test_utf8_stdio_only_on_windows():
    def stream():
        return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    s = stream()
    paths.utf8_stdio("darwin", [s])
    assert s.encoding == "cp1252"
    paths.utf8_stdio("win32", [s, None])
    assert s.encoding == "utf-8"
    s.write("こんにちは")  # cp1252 could not encode this


# --- device names and host API ---

def test_meeting_cables_and_host_api_defaults():
    assert audio.meeting_cables("darwin") == ("BlackHole 2ch", "BlackHole 16ch")
    assert audio.meeting_cables("win32") == ("CABLE-A", "CABLE-B")
    assert audio.default_host_api("darwin") is None
    assert audio.default_host_api("win32") == "wasapi"


def test_cable_name_finds_the_end_of_each_kind_in_wasapi():
    assert find("CABLE-A", "output") == 10  # the engine writes to CABLE-A Input
    assert find("CABLE-B", "input") == 8    # and captures CABLE-B Output
    assert find("Headphones", "output") == 9


def test_host_api_default_devices_replace_the_mme_mapper():
    assert find(None, "input") == 6
    assert find(None, "output") == 9
    assert audio.find_device(None, "input", WIN_DEVICES) is None  # no host API: PortAudio's default


def test_name_of_the_other_end_matches_a_cable():
    assert find("CABLE-A Output", "output") == 10  # what Meet shows as its microphone
    assert find("CABLE-B Input", "input") == 8     # what Meet shows as its speaker
    with pytest.raises(audio.DeviceError):         # not for physical devices
        find("Headphones Input", "output")


def test_mme_truncated_names_match_full_names():
    assert find("CABLE-A Input (VB-Audio Cable A)", "output", "mme") == 5
    assert find("CABLE-B Output (VB-Audio Cable B)", "input", "mme") == 3
    assert find("CABLE-B", "input", "mme") == 3


def test_unknown_host_api_names_the_choices():
    with pytest.raises(audio.DeviceError, match="MME, Windows WASAPI"):
        find("CABLE-A", "output", "asio")


def test_devices_json_filters_by_host_api():
    j = cli.devices_json(WIN_DEVICES, 1)
    assert [d["index"] for d in j["inputs"]] == [6, 7, 8]
    assert [d["index"] for d in j["outputs"]] == [9, 10, 11]
    assert len(cli.devices_json(WIN_DEVICES)["inputs"]) == 7  # no filter: as before


def test_virtual_cable_names():
    for n in ("BlackHole 2ch", "CABLE Input (VB-Audio Virtual Cable)", "CABLE-A Output (VB-Audio Cable ",
              "Line 1 (Virtual Audio Cable)"):
        assert audio.is_virtual_cable(n), n
    for n in ("Headphones (Realtek(R) Audio)", "MacBook Pro Microphone", "AirPods Pro", None):
        assert not audio.is_virtual_cable(n), n
    assert audio.cable_id("CABLE-A Input (VB-Audio Cable A)") == audio.cable_id("CABLE-A Output (VB-Audio Cable ")
    assert audio.cable_id("CABLE-A Input (VB-Audio Cable A)") != audio.cable_id("CABLE-B Input (VB-Audio Cable B)")
    assert audio.cable_id("BlackHole 2ch") == "blackhole 2ch"


def test_capture_options_low_latency_for_windows_cables():
    assert audio.capture_options("CABLE-B Output (VB-Audio Cable B)") == {"latency": "low", "block_ms": 10}
    assert audio.capture_options("Microphone (Realtek(R) Audio)") == {}


def routes(spk="Headphones (Realtek(R) Audio)", mic="Microphone (Realtek(R) Audio)",
           meet_spk="CABLE-B Output (VB-Audio Cable B)", meet_mic="CABLE-A Input (VB-Audio Cable A)"):
    return {"IN": ((8, meet_spk), (9, spk)), "OUT": ((6, mic), (10, meet_mic))}


def test_check_passthrough_with_vb_cables():
    audio.check_passthrough(routes())
    with pytest.raises(audio.DeviceError, match="a virtual audio cable"):
        audio.check_passthrough(routes(spk="CABLE-A Input (VB-Audio Cable A)"))
    with pytest.raises(audio.DeviceError, match="feedback loop"):  # writes into the cable it captures
        audio.check_passthrough(routes(meet_mic="CABLE-B Input (VB-Audio Cable B)"))
    with pytest.raises(audio.DeviceError, match="feedback loop"):
        audio.check_passthrough(routes(mic="CABLE-A Output (VB-Audio Cable A)"))


# --- terminal push-to-talk without termios ---

async def test_ptt_reads_console_keys_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "stdin", type("TTY", (), {"isatty": lambda self: True})())
    keys = iter([" ", "x", "q"])
    gate = asyncio.Event()

    def getwch():
        try:
            return next(keys)
        except StopIteration:
            raise EOFError

    p = PTT(muted=True, out=lambda *_: None)
    loop = asyncio.get_running_loop()
    assert p.attach(loop, gate.set, platform="win32", getwch=getwch)
    await asyncio.wait_for(gate.wait(), 2)
    assert p.muted is False  # space toggled, x ignored, q quit
    p.detach()
