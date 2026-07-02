"""Pytest setup for the device tree.

The device package is imported as ``lib.prestodeck.*`` (the same path the board
uses), so put this ``device/`` directory on ``sys.path``. The device modules are
written to import cleanly on host CPython -- hardware-only imports (``presto``,
``ezwifi``, ...) are reached lazily inside functions, never at import time.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
