"""PrestoDeck device library.

This package contains the on-device (Pimoroni Presto / MicroPython) runtime for
PrestoDeck: the WebSocket client, the mDNS discovery helper, the wire protocol
codec, the picographics-backed UI surface, touch/swipe input, and the icon
cache.

All modules in this package are written to be MicroPython-compatible. They avoid
host-only constructs (e.g. ``from __future__ import annotations``) and guard any
imports of device-frozen modules so the tree still parses under host CPython.
"""

__version__ = "0.1.0"
