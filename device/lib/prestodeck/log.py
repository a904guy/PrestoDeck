"""Leveled logging for PrestoDeck (device side).

This is the single sanctioned output sink for the device firmware. No other
module may call the built-in ``print``; everything routes through the
``debug``/``info``/``warn``/``error`` functions exposed here. This module is
the one place permitted to use ``print`` internally as the underlying sink.
"""

# Numeric severities. Kept as plain ints so comparisons are MicroPython-cheap.
DEBUG = 10
INFO = 20
WARN = 30
ERROR = 40

_LEVEL_NAMES = {
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARN: "WARN",
    ERROR: "ERROR",
}

# Active threshold. Records below this level are suppressed.
_level = INFO


def set_level(level):
    """Set the minimum severity that will be emitted.

    :param level: one of DEBUG/INFO/WARN/ERROR.
    """
    global _level
    _level = level


def _emit(level, msg):
    """Format and write a single record to the sink.

    A guarded ``print`` -- the only permitted ``print`` in the codebase.
    """
    if level < _level:
        return
    print("[" + _LEVEL_NAMES.get(level, "?") + "] " + str(msg))


def debug(msg):
    """Emit a DEBUG-level record."""
    _emit(DEBUG, msg)


def info(msg):
    """Emit an INFO-level record."""
    _emit(INFO, msg)


def warn(msg):
    """Emit a WARN-level record."""
    _emit(WARN, msg)


def error(msg):
    """Emit an ERROR-level record."""
    _emit(ERROR, msg)
