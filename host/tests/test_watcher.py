"""Tests for the config watcher's reload-and-validate behaviour."""

from __future__ import annotations

from pathlib import Path

from prestodeck_host.config import DeckConfig
from prestodeck_host.watcher import ConfigWatcher

_VALID = """
version: 1
default_page: main
pages:
  - id: main
    grid: [1, 1]
    buttons:
      - {id: a, row: 0, col: 0, label: First}
"""

_INVALID = """
version: 1
default_page: ghost
pages:
  - id: main
    grid: [1, 1]
    buttons: []
"""


async def test_watcher_reloads_valid_and_keeps_last_good(tmp_path: Path) -> None:
    """A valid edit triggers the callback; an invalid one is skipped (last-good kept)."""
    deck = tmp_path / "deck.yaml"
    deck.write_text(_VALID, encoding="utf-8")
    reloaded: list[DeckConfig] = []

    async def on_reload(config: DeckConfig) -> None:
        reloaded.append(config)

    watcher = ConfigWatcher(deck, tmp_path / "icons", on_reload)

    await watcher._reload_once()
    assert len(reloaded) == 1
    assert reloaded[0].pages[0].buttons[0].label == "First"

    # An invalid edit must NOT fire the callback (server keeps the last-good config).
    deck.write_text(_INVALID, encoding="utf-8")
    await watcher._reload_once()
    assert len(reloaded) == 1
