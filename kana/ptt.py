"""Push-to-talk from the terminal: space toggles outbound live/muted, q quits.
Uses cbreak mode on stdin; no hotkey library and no Accessibility permission."""
from __future__ import annotations

import asyncio
import sys


class PTT:
    def __init__(self, muted: bool = True, out=print):
        self.muted = muted
        self.out = out
        self._saved = None

    def state(self) -> str:
        return "MUTED (space = talk)" if self.muted else "LIVE  (space = mute)"

    def toggle(self) -> None:
        self.muted = not self.muted
        self.out(f"[PTT] outbound {self.state()}")

    def handle_key(self, ch: str) -> str | None:
        if ch == " ":
            self.toggle()
            return "toggle"
        if ch in ("q", "Q"):
            return "quit"
        return None

    def attach(self, loop: asyncio.AbstractEventLoop, on_quit) -> bool:
        """Read keys from a TTY stdin. Returns False when stdin is not a TTY."""
        if not sys.stdin.isatty():
            return False
        import termios
        import tty
        fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)

        def on_key():
            ch = sys.stdin.read(1)
            if self.handle_key(ch) == "quit":
                on_quit()

        loop.add_reader(fd, on_key)
        self._loop = loop
        return True

    def detach(self) -> None:
        if self._saved is None:
            return
        import termios
        fd = sys.stdin.fileno()
        self._loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, self._saved)
        self._saved = None
