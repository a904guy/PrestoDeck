"""Shared keyboard/media injection helpers for input actions.

Two backends are supported and chosen automatically:

* ``pynput`` (X11/XTEST) on X11 sessions.
* ``ydotool`` (kernel uinput) on Wayland, where pynput's XTEST injection is
  misrouted by the compositor. Requires the ``ydotool`` binary and a running
  ``ydotoold`` daemon.

Override the choice with the ``PRESTODECK_INPUT_BACKEND`` env var
(``pynput`` or ``ydotool``). ``parse_combo`` is pure and unit-testable without
either backend; key-name resolution happens only at injection time.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from prestodeck_host.actions import _uinput
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

_keyboard: Any = None
_warned = False

# --- shared parsing -------------------------------------------------------

# Modifier token -> pynput Key attribute name.
_MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "cmd": "cmd",
    "command": "cmd",
    "super": "cmd",
    "win": "cmd",
    "meta": "cmd",
}

# Named (non-character) key token -> pynput Key attribute name.
_NAMED_KEYS = {
    "space": "space",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "esc": "esc",
    "escape": "esc",
    "backspace": "backspace",
    "delete": "delete",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "pageup": "page_up",
    "pagedown": "page_down",
}

# Media key token -> pynput Key attribute name.
_MEDIA_KEYS = {
    "play_pause": "media_play_pause",
    "next": "media_next",
    "prev": "media_previous",
    "previous": "media_previous",
    "vol_up": "media_volume_up",
    "vol_down": "media_volume_down",
    "mute": "media_volume_mute",
}


def parse_combo(combo: str) -> tuple[list[str], str]:
    """Split a combo like ``"ctrl+shift+t"`` into ``(modifiers, key)``. Pure.

    :raises ValueError: if the combo is empty.
    """
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty key combo")
    return parts[:-1], parts[-1]


# --- backend selection ----------------------------------------------------


def _backend() -> str:
    """Return the active input backend: ``"uinput"``, ``"ydotool"``, or ``"pynput"``.

    On Wayland, pynput's XTEST injection is misrouted, so prefer direct uinput
    (no daemon, when ``/dev/uinput`` is writable) then ydotool.
    """
    override = os.environ.get("PRESTODECK_INPUT_BACKEND", "").lower()
    if override in ("pynput", "ydotool", "uinput"):
        return override
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        if _uinput.UInputKeyboard.writable():
            return "uinput"
        if shutil.which("ydotool"):
            return "ydotool"
    return "pynput"


def _warn_backend_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    if _backend() == "pynput" and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        _logger.warning(
            "Wayland session with no usable injector: pynput's XTEST is misrouted "
            "here. Grant your user write access to /dev/uinput, or install ydotool."
        )


# --- pynput backend -------------------------------------------------------


def _get_keyboard() -> Any:
    """Return a cached pynput keyboard Controller (lazy import)."""
    global _keyboard
    if _keyboard is None:
        from pynput.keyboard import Controller

        _keyboard = Controller()
    return _keyboard


def _resolve_key(token: str) -> Any:
    """Resolve a key token to a pynput key object or a single character."""
    from pynput.keyboard import Key

    if token in _NAMED_KEYS:
        return getattr(Key, _NAMED_KEYS[token])
    if token.startswith("f") and token[1:].isdigit():
        return getattr(Key, token)
    return token


def _pynput_combo(combo: str) -> None:
    from pynput.keyboard import Key

    modifiers, key_token = parse_combo(combo)
    keyboard = _get_keyboard()
    mod_keys = [getattr(Key, _MODIFIERS[m]) for m in modifiers if m in _MODIFIERS]
    target = _resolve_key(key_token)
    for mod in mod_keys:
        keyboard.press(mod)
    try:
        keyboard.press(target)
        keyboard.release(target)
    finally:
        for mod in reversed(mod_keys):
            keyboard.release(mod)


def _pynput_media(key: str) -> None:
    from pynput.keyboard import Key

    media = getattr(Key, _MEDIA_KEYS[key])
    keyboard = _get_keyboard()
    keyboard.press(media)
    keyboard.release(media)


# --- ydotool backend (Linux evdev keycodes) -------------------------------

_YD_MODIFIERS = {
    "ctrl": 29,
    "control": 29,
    "shift": 42,
    "alt": 56,
    "option": 56,
    "cmd": 125,
    "command": 125,
    "super": 125,
    "win": 125,
    "meta": 125,
}

_YD_KEYS = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "space": 57, "enter": 28, "return": 28, "tab": 15, "esc": 1, "escape": 1,
    "backspace": 14, "delete": 111, "up": 103, "down": 108, "left": 105, "right": 106,
    "home": 102, "end": 107, "pageup": 104, "pagedown": 109,
}

_YD_MEDIA = {
    "play_pause": 164,
    "next": 163,
    "prev": 165,
    "previous": 165,
    "vol_up": 115,
    "vol_down": 114,
    "mute": 113,
}


def _ydotool(args: list[str]) -> None:
    """Run ydotool with the given arguments, raising on failure."""
    subprocess.run(["ydotool", *args], check=True, capture_output=True, text=True)


def _ydotool_combo(combo: str) -> None:
    modifiers, key_token = parse_combo(combo)
    codes = [_YD_MODIFIERS[m] for m in modifiers if m in _YD_MODIFIERS]
    if key_token not in _YD_KEYS:
        raise ValueError(f"ydotool: unsupported key {key_token!r}")
    keycode = _YD_KEYS[key_token]
    seq = (
        [f"{c}:1" for c in codes]
        + [f"{keycode}:1", f"{keycode}:0"]
        + [f"{c}:0" for c in reversed(codes)]
    )
    _ydotool(["key", *seq])


def _ydotool_media(key: str) -> None:
    code = _YD_MEDIA[key]
    _ydotool(["key", f"{code}:1", f"{code}:0"])


# --- uinput backend (direct /dev/uinput, reuses the evdev keycodes) -------

# char -> (keycode, modifier keycodes) for the type() best-effort path.
_UINPUT_CHARMAP: dict[str, tuple[int, tuple[int, ...]]] = {}
for _ch, _code in _YD_KEYS.items():
    if len(_ch) == 1:  # a-z, 0-9
        _UINPUT_CHARMAP[_ch] = (_code, ())
_UINPUT_CHARMAP[" "] = (57, ())
for _ch in "abcdefghijklmnopqrstuvwxyz":
    _UINPUT_CHARMAP[_ch.upper()] = (_YD_KEYS[_ch], (42,))
_UINPUT_CHARMAP.update(
    {
        ".": (52, ()), ",": (51, ()), "/": (53, ()), "-": (12, ()), "=": (13, ()),
        ";": (39, ()), "'": (40, ()), "\n": (28, ()),
    }
)

# Every keycode the virtual device must enable.
_UINPUT_KEYCODES = (
    set(_YD_MODIFIERS.values())
    | set(_YD_KEYS.values())
    | set(_YD_MEDIA.values())
    | {code for code, _ in _UINPUT_CHARMAP.values()}
    | {42}
)


def _uinput_kb() -> Any:
    return _uinput.keyboard(_UINPUT_KEYCODES)


def _uinput_combo(combo: str) -> None:
    modifiers, key_token = parse_combo(combo)
    mods = tuple(_YD_MODIFIERS[m] for m in modifiers if m in _YD_MODIFIERS)
    if key_token not in _YD_KEYS:
        raise ValueError(f"uinput: unsupported key {key_token!r}")
    _uinput_kb().tap(_YD_KEYS[key_token], mods)


def _uinput_media(key: str) -> None:
    _uinput_kb().tap(_YD_MEDIA[key])


# --- public API (dispatches to the active backend) ------------------------


def tap_combo(combo: str) -> None:
    """Press a key combination (modifiers held around the final key)."""
    _warn_backend_once()
    backend = _backend()
    if backend == "uinput":
        _uinput_combo(combo)
    elif backend == "ydotool":
        _ydotool_combo(combo)
    else:
        _pynput_combo(combo)


def type_text(text: str) -> None:
    """Type a literal string at the host cursor."""
    _warn_backend_once()
    backend = _backend()
    if backend == "uinput":
        _uinput_kb().type_chars(text, _UINPUT_CHARMAP)
    elif backend == "ydotool":
        _ydotool(["type", text])
    else:
        _get_keyboard().type(text)


def tap_media(key: str) -> None:
    """Tap a media key by logical name (e.g. ``play_pause``).

    :raises ValueError: if ``key`` is not a known media key.
    """
    if key not in _MEDIA_KEYS:
        raise ValueError(f"unknown media key: {key}")
    _warn_backend_once()
    backend = _backend()
    if backend == "uinput":
        _uinput_media(key)
    elif backend == "ydotool":
        _ydotool_media(key)
    else:
        _pynput_media(key)
