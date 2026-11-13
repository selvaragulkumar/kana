"""Push-to-talk from the terminal: space toggles outbound live/muted, q quits.
Uses cbreak mode on stdin (msvcrt on Windows); no hotkey library and no Accessibility permission."""
from __future__ import annotations

import asyncio
import sys


class PTT:
    def __init__(self, muted: bool = True, out=print):
        self.muted = muted
        self.out = out
        self._saved = None
        self._reading = False

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

    def attach(self, loop: asyncio.AbstractEventLoop, on_quit, platform: str | None = None,
               getwch=None) -> bool:
        """Read keys from a TTY stdin. Returns False when stdin is not a TTY.
        On Windows there is no termios and the asyncio loop has no add_reader, so
        a daemon thread reads keys with msvcrt.getwch (`getwch` replaces it in tests)."""
        if not sys.stdin.isatty():
            return False
        if (sys.platform if platform is None else platform) == "win32":
            return self._attach_console(loop, on_quit, getwch)
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

    def _attach_console(self, loop, on_quit, getwch=None) -> bool:
        import threading
        if getwch is None:
            import msvcrt
            getwch = msvcrt.getwch
        self._reading = True

        def on_key(ch):
            if self._reading and self.handle_key(ch) == "quit":
                on_quit()

        def reader():
            while self._reading:
                try:
                    ch = getwch()
                except Exception:
                    return
                try:
                    loop.call_soon_threadsafe(on_key, ch)
                except RuntimeError:  # loop closed
                    return

        self._thread = threading.Thread(target=reader, name="ptt-keys", daemon=True)
        self._thread.start()
        return True

    def detach(self) -> None:
        self._reading = False  # a Windows reader thread stops at its next key (daemon)
        if self._saved is None:
            return
        import termios
        fd = sys.stdin.fileno()
        self._loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, self._saved)
        self._saved = None
