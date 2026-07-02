"""Logging helpers for the PrestoDeck host.

Thin wrapper over the stdlib :mod:`logging` module so that the rest of the
codebase never touches ``logging`` directly and never uses ``print``.
"""

from __future__ import annotations

import logging

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once for the process.

    Idempotent: repeated calls after the first are no-ops so that library use
    and the console-script entry point do not install duplicate handlers.
    """
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_DEFAULT_FORMAT)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger.

    Callers should pass ``__name__`` so log records carry the module path.
    """
    return logging.getLogger(name)
