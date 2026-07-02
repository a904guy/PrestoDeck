"""Persistent host state for stateful actions (e.g. toggle).

A small JSON-backed key/value store under the XDG state directory
(``~/.local/state/prestodeck/state.json`` by default). Writes are atomic
(temp file + replace). Keys are namespaced by the caller (toggle uses
``<device_id>:<toggle_id>``) so per-device state never collides.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from prestodeck_host.log import get_logger

_logger = get_logger(__name__)


def default_state_path() -> Path:
    """Return the default state file path, honouring ``XDG_STATE_HOME``."""
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "prestodeck" / "state.json"


class StateStore:
    """A JSON-backed key/value store persisted atomically to disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_state_path()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Return the stored value for ``key`` or ``default``."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set ``key`` to ``value`` and persist the store atomically."""
        self._data[key] = value
        self._persist()

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self._path)
        except OSError as exc:
            _logger.warning("failed to persist state to %s: %s", self._path, exc)
