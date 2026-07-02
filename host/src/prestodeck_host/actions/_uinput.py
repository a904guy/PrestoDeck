"""Direct Linux ``/dev/uinput`` key injection (no daemon, stdlib only).

This is the preferred input backend on Wayland when the host user can write
``/dev/uinput`` (commonly via an ACL or the ``input`` group). It creates one
persistent virtual keyboard and emits evdev key events through it, so it needs
neither a separate daemon (unlike ydotool) nor an X server (unlike pynput).

Keycodes are the Linux ``input-event-codes.h`` values.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import struct
import time

from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

UINPUT_PATH = "/dev/uinput"

# evdev event types / codes.
_EV_SYN = 0
_EV_KEY = 1
_SYN_REPORT = 0

# uinput ioctls: _IOW/_IO('U', nr, size). dir<<30 | size<<16 | type<<8 | nr.
_U = ord("U")


def _iow(nr: int, size: int) -> int:
    return (1 << 30) | (size << 16) | (_U << 8) | nr


def _io(nr: int) -> int:
    return (_U << 8) | nr


_UI_SET_EVBIT = _iow(100, 4)
_UI_SET_KEYBIT = _iow(101, 4)
_UI_DEV_SETUP = _iow(3, 92)  # sizeof(struct uinput_setup) on x86-64
_UI_DEV_CREATE = _io(1)
_UI_DEV_DESTROY = _io(2)

# input_event: struct timeval (2x long) + type(u16) + code(u16) + value(i32).
_EVENT_FMT = "llHHi"


class UInputKeyboard:
    """A persistent virtual keyboard backed by ``/dev/uinput``."""

    def __init__(self, keycodes: set[int]) -> None:
        self._keycodes = keycodes
        self._fd: int | None = None

    @staticmethod
    def writable() -> bool:
        """Return whether ``/dev/uinput`` can be opened for writing."""
        return os.access(UINPUT_PATH, os.W_OK)

    def _ensure(self) -> None:
        if self._fd is not None:
            return
        fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(fd, _UI_SET_EVBIT, _EV_KEY)
        for code in self._keycodes:
            fcntl.ioctl(fd, _UI_SET_KEYBIT, code)
        # struct uinput_setup: input_id(bustype, vendor, product, version) +
        # name[80] + ff_effects_max(u32).
        setup = (
            struct.pack("HHHH", 0x03, 0x1234, 0x5678, 1)
            + b"PrestoDeck Virtual Keyboard".ljust(80, b"\x00")
            + struct.pack("I", 0)
        )
        fcntl.ioctl(fd, _UI_DEV_SETUP, setup)
        fcntl.ioctl(fd, _UI_DEV_CREATE)
        # The compositor needs a moment to enumerate the new device.
        time.sleep(0.3)
        self._fd = fd
        _logger.info("uinput virtual keyboard created")

    def _emit(self, etype: int, code: int, value: int) -> None:
        assert self._fd is not None
        os.write(self._fd, struct.pack(_EVENT_FMT, 0, 0, etype, code, value))

    def _syn(self) -> None:
        self._emit(_EV_SYN, _SYN_REPORT, 0)

    def tap(self, keycode: int, modifiers: tuple[int, ...] = ()) -> None:
        """Press ``keycode`` with ``modifiers`` held, then release everything."""
        self._ensure()
        for mod in modifiers:
            self._emit(_EV_KEY, mod, 1)
        self._syn()
        self._emit(_EV_KEY, keycode, 1)
        self._syn()
        self._emit(_EV_KEY, keycode, 0)
        self._syn()
        for mod in reversed(modifiers):
            self._emit(_EV_KEY, mod, 0)
        self._syn()

    def type_chars(self, text: str, keymap: dict[str, tuple[int, tuple[int, ...]]]) -> None:
        """Type ``text`` using a char -> (keycode, modifiers) map (best effort)."""
        for ch in text:
            entry = keymap.get(ch)
            if entry is None:
                continue
            keycode, mods = entry
            self.tap(keycode, mods)

    def close(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                fcntl.ioctl(self._fd, _UI_DEV_DESTROY)
            os.close(self._fd)
            self._fd = None


_keyboard: UInputKeyboard | None = None


def keyboard(keycodes: set[int]) -> UInputKeyboard:
    """Return a process-wide cached :class:`UInputKeyboard`."""
    global _keyboard
    if _keyboard is None:
        _keyboard = UInputKeyboard(keycodes)
    return _keyboard
