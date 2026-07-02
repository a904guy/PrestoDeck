"""Config file watcher for hot reload.

Watches the deck YAML file and the icons directory with ``watchfiles``. On any
change it revalidates the deck; on success it invokes the reload callback (the
server pushes the new config to every connected device), and on failure it logs
a diagnostic and keeps the last-good config (the running server is untouched).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from watchfiles import awatch

from prestodeck_host.config import DeckConfig, DeckConfigError, load_deck
from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

ReloadCallback = Callable[[DeckConfig], Awaitable[None]]


class ConfigWatcher:
    """Watches the deck file + icons dir and reloads/pushes on change."""

    def __init__(self, deck_path: Path, icons_dir: Path, on_reload: ReloadCallback) -> None:
        self._deck_path = deck_path
        self._icons_dir = icons_dir
        self._on_reload = on_reload

    async def watch_forever(self) -> None:
        """Watch for changes until cancelled, reloading on each."""
        watch_paths = [str(self._deck_path.parent)]
        if self._icons_dir.exists() and self._icons_dir.parent != self._deck_path.parent:
            watch_paths.append(str(self._icons_dir))
        _logger.info("watching for config changes under %s", ", ".join(watch_paths))
        async for _changes in awatch(*watch_paths):
            await self._reload_once()

    async def _reload_once(self) -> None:
        try:
            config = load_deck(self._deck_path, self._icons_dir)
        except DeckConfigError as exc:
            _logger.error("config reload rejected, keeping last-good config:\n%s", exc)
            return
        await self._on_reload(config)
