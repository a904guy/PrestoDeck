"""Every shipped example deck must validate against the real schema + icons.

Keeps `examples/*.yaml` from rotting: if a field is renamed or an example
references a missing icon or unknown page, CI fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prestodeck_host.config import load_deck

_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = sorted((_ROOT / "examples").glob("*.yaml"))
_ICONS = _ROOT / "host" / "config" / "icons"


def test_examples_present() -> None:
    """Guard against the glob silently finding nothing (wrong path/rename)."""
    assert _EXAMPLES, "no example decks found under examples/"


@pytest.mark.parametrize("path", _EXAMPLES, ids=lambda p: p.name)
def test_example_deck_validates(path: Path) -> None:
    deck = load_deck(path, _ICONS)
    assert deck.pages
    assert any(page.id == deck.default_page for page in deck.pages)
