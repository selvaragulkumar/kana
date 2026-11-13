"""Per-platform locations and console setup. macOS is the shipped platform;
the Windows and Linux branches are groundwork (docs/research/windows.md) and
are only unit-tested, not yet run on those systems."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "kana"


def support_dir(platform: str | None = None, env=None, home: Path | None = None) -> Path:
    """The engine's data folder; transcripts go to <support_dir>/transcripts.

    macOS: ~/Library/Application Support/kana (unchanged, the app uses the same folder).
    Windows: %LOCALAPPDATA%\\kana. Local, not Roaming: engine_path and device names
    are machine-specific, and transcripts should not sync with a roaming profile.
    Other systems: $XDG_DATA_HOME/kana, else ~/.local/share/kana."""
    platform = sys.platform if platform is None else platform
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_FOLDER
    if platform == "win32":
        base = env.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP_FOLDER
    base = env.get("XDG_DATA_HOME")
    return (Path(base) if base else home / ".local" / "share") / APP_FOLDER


SUPPORT_DIR_HELP = "~/Library/Application Support/kana on macOS, %%LOCALAPPDATA%%\\kana on Windows"


def utf8_stdio(platform: str | None = None, streams=None) -> None:
    """On Windows a piped stdout uses the ANSI code page (cp1252, cp932), which
    cannot encode every transcript; the JSON protocol is UTF-8 (docs/ENGINE.md).
    Elsewhere the streams are left as they are."""
    platform = sys.platform if platform is None else platform
    if platform != "win32":
        return
    for s in (sys.stdin, sys.stdout, sys.stderr) if streams is None else streams:
        if s is not None and hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
