"""Icon store: manifest computation and streaming to the device.

Icons are pre-rasterized PNGs under ``host/config/icons/``. The
store computes a sha256 manifest the device diffs against its local cache, and
serves icon bytes in base64 chunks over the ``icon_chunk`` message when the
device sends ``request_icon``.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

# Binary bytes per icon_chunk (base64 expands this by ~4/3 on the wire).
CHUNK_BYTES = 4096

# Icon file extensions the store will serve.
_ICON_SUFFIXES = (".png",)


class IconStore:
    """Resolves icon names to manifest entries and base64 stream chunks."""

    def __init__(self, icon_dir: Path) -> None:
        self._icon_dir = icon_dir

    def manifest(self) -> list[dict[str, Any]]:
        """Return ``[{"name", "sha256", "size"}, ...]`` for every icon on disk.

        Names are the file names relative to the icon directory; the device uses
        them verbatim as cache keys.
        """
        entries: list[dict[str, Any]] = []
        if not self._icon_dir.is_dir():
            _logger.warning("icon dir %s does not exist", self._icon_dir)
            return entries
        for path in sorted(self._icon_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _ICON_SUFFIXES:
                continue
            data = path.read_bytes()
            entries.append(
                {
                    "name": path.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
        return entries

    def read(self, name: str) -> bytes | None:
        """Return the raw bytes of icon ``name``, or ``None`` if absent/invalid.

        The name is treated as a bare file name; path separators are rejected to
        keep reads inside the icon directory.
        """
        if "/" in name or "\\" in name or name in ("", ".", ".."):
            _logger.warning("rejecting suspicious icon name %r", name)
            return None
        path = self._icon_dir / name
        if not path.is_file():
            _logger.warning("requested icon %r not found", name)
            return None
        return path.read_bytes()

    def chunks(self, name: str) -> list[dict[str, Any]] | None:
        """Return the ``icon_chunk`` payloads for ``name``, or ``None`` if absent.

        Each payload is ``{"name", "seq", "total", "data_b64"}``; ``total`` is the
        chunk count so the device knows when reassembly is complete.
        """
        data = self.read(name)
        if data is None:
            return None
        total = max(1, (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES)
        payloads: list[dict[str, Any]] = []
        for seq in range(total):
            blob = data[seq * CHUNK_BYTES : (seq + 1) * CHUNK_BYTES]
            payloads.append(
                {
                    "name": name,
                    "seq": seq,
                    "total": total,
                    "data_b64": base64.b64encode(blob).decode("ascii"),
                }
            )
        return payloads
