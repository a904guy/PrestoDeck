"""PrestoDeck host package.

The host is a long-lived async daemon that serves a WebSocket endpoint to one
or more PrestoDeck devices, advertises itself over mDNS, validates a YAML deck
configuration, and runs an action engine for button presses.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("prestodeck-host")
except PackageNotFoundError:  # not installed (e.g. running from a source checkout)
    __version__ = "0.1.0"
