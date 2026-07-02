"""Monotonic-time and sleep helpers that work on MicroPython and host CPython.

MicroPython exposes ``time.ticks_ms`` / ``time.ticks_diff`` and
``asyncio.sleep_ms``; host CPython does not. These shims pick the right
primitive so the rest of the device code calls one helper instead of repeating
the ``hasattr`` dance at every call site.
"""

import time


def ticks_ms():
    """Return a monotonic millisecond counter (wraps on MicroPython)."""
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def ticks_add(t, delta):
    """Return ``t + delta`` ms, honouring MicroPython tick wraparound."""
    if hasattr(time, "ticks_add"):
        return time.ticks_add(t, delta)
    return t + delta


def ticks_diff(a, b):
    """Return ``a - b`` in ms, honouring MicroPython tick wraparound."""
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


async def sleep_ms(ms):
    """Sleep for ``ms`` milliseconds on either runtime."""
    import asyncio

    if hasattr(asyncio, "sleep_ms"):
        await asyncio.sleep_ms(ms)
    else:
        await asyncio.sleep(ms / 1000)
