"""Tests for deck config loading, validation, and device resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from prestodeck_host.config import DeckConfigError, load_deck, resolve_for_device

_VALID = """
version: 1
default_page: main
theme:
  background: [10, 10, 14]
  default_outline_color: [29, 185, 84]
pages:
  - id: main
    grid: [2, 2]
    buttons:
      - id: b1
        row: 0
        col: 0
        label: One
        color: [231, 72, 86]
      - id: go
        row: 0
        col: 1
        label: Macros
        action: {type: navigate, page: macros}
  - id: macros
    grid: [2, 2]
    buttons:
      - id: back
        row: 0
        col: 0
        label: Back
        action: {type: navigate, page: main}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "deck.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_deck(tmp_path: Path) -> None:
    """A valid deck loads and exposes pages keyed by id."""
    deck = load_deck(_write(tmp_path, _VALID))
    assert deck.default_page == "main"
    assert [p.id for p in deck.pages] == ["main", "macros"]
    assert [b.id for b in deck.pages[0].buttons] == ["b1", "go"]


def test_resolve_for_device_shape(tmp_path: Path) -> None:
    """Resolution emits the device config wire shape with display-only fields."""
    deck = load_deck(_write(tmp_path, _VALID))
    payload = resolve_for_device(deck, [{"name": "x.png", "sha256": "ab", "size": 3}])
    assert payload["version"] == 1
    assert payload["default_page"] == "main"
    assert payload["icons_manifest"] == [{"name": "x.png", "sha256": "ab", "size": 3}]
    main = payload["pages"][0]
    assert main["id"] == "main"
    assert main["grid"] == [2, 2]
    b1 = main["buttons"][0]
    assert b1 == {
        "id": "b1",
        "row": 0,
        "col": 0,
        "label": "One",
        "color": [231, 72, 86],
        "icon": None,
    }
    # Actions stay on the host: not present in the resolved device payload.
    assert "action" not in b1
    # A button without repeat_ms does not carry the field in the device payload.
    assert "repeat_ms" not in b1


def test_repeat_ms_resolves_to_device(tmp_path: Path) -> None:
    """A button with repeat_ms carries it into the device payload; <=0 is rejected."""
    text = _VALID.replace(
        "        label: One\n", "        label: One\n        repeat_ms: 120\n"
    )
    deck = load_deck(_write(tmp_path, text))
    payload = resolve_for_device(deck, [])
    assert payload["pages"][0]["buttons"][0]["repeat_ms"] == 120

    bad = _VALID.replace("        label: One\n", "        label: One\n        repeat_ms: 0\n")
    with pytest.raises(DeckConfigError):
        load_deck(_write(tmp_path, bad))


def test_overlapping_buttons_rejected(tmp_path: Path) -> None:
    """Two buttons in the same grid cell are a validation error."""
    text = _VALID.replace(
        "        col: 1\n        label: Macros", "        col: 0\n        label: Macros"
    )
    with pytest.raises(DeckConfigError, match="overlaps"):
        load_deck(_write(tmp_path, text))


def test_out_of_bounds_button_rejected(tmp_path: Path) -> None:
    """A button outside its page grid is a validation error."""
    text = _VALID.replace(
        "        col: 1\n        label: Macros", "        col: 5\n        label: Macros"
    )
    with pytest.raises(DeckConfigError, match="outside"):
        load_deck(_write(tmp_path, text))


def test_navigate_to_unknown_page_rejected(tmp_path: Path) -> None:
    """A navigate action targeting a missing page is a validation error."""
    text = _VALID.replace("page: macros}", "page: nowhere}")
    with pytest.raises(DeckConfigError, match="unknown page"):
        load_deck(_write(tmp_path, text))


def test_yaml_syntax_error_reports_line(tmp_path: Path) -> None:
    """A YAML syntax error refuses to load with a line reference."""
    with pytest.raises(DeckConfigError, match="line"):
        load_deck(_write(tmp_path, "version: 1\n  bad: : indent\n"))


def test_toggle_on_off_keys_are_strings(tmp_path: Path) -> None:
    """YAML ``on:``/``off:`` keys load as strings, not booleans (toggle action)."""
    text = """
version: 1
default_page: main
pages:
  - id: main
    grid: [1, 1]
    buttons:
      - id: mic
        row: 0
        col: 0
        action:
          type: toggle
          id: mic
          on: {type: notify, text: up}
          off: {type: notify, text: down}
"""
    deck = load_deck(_write(tmp_path, text))
    action = deck.pages[0].buttons[0].action
    assert action is not None
    assert action.on == {"type": "notify", "text": "up"}
    assert action.off == {"type": "notify", "text": "down"}


def test_missing_icon_rejected(tmp_path: Path) -> None:
    """A referenced icon that is absent from the icons dir is rejected."""
    text = _VALID.replace("        label: One\n", "        label: One\n        icon: missing.png\n")
    icons = tmp_path / "icons"
    icons.mkdir()
    with pytest.raises(DeckConfigError, match="missing icon"):
        load_deck(_write(tmp_path, text), icons_dir=icons)
