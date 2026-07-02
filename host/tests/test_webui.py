"""Web UI API tests: deck get/put/preview, validation safety, icon upload."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from prestodeck_host.webui.app import create_app

_VALID = """
version: 1
default_page: main
pages:
  - id: main
    grid: [1, 1]
    buttons:
      - {id: a, row: 0, col: 0, label: First}
"""

_INVALID = "version: 1\ndefault_page: ghost\npages: []\n"


def _client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    deck = tmp_path / "deck.yaml"
    deck.write_text(_VALID, encoding="utf-8")
    icons = tmp_path / "icons"
    icons.mkdir()
    return TestClient(create_app(deck, icons, ws_port=7878)), deck, icons


def test_get_and_preview_deck(tmp_path: Path) -> None:
    """GET returns the YAML; preview validates and returns resolved pages."""
    client, _deck, _icons = _client(tmp_path)
    assert "default_page" in client.get("/api/deck").text

    r = client.post("/api/deck/preview", json={"yaml": _VALID})
    assert r.status_code == 200
    assert r.json()["pages"][0]["buttons"][0]["label"] == "First"

    bad = client.post("/api/deck/preview", json={"yaml": _INVALID})
    assert bad.status_code == 400


def test_put_valid_saves_and_invalid_does_not_corrupt(tmp_path: Path) -> None:
    """A valid PUT writes deck.yaml; an invalid PUT is rejected and the file is intact."""
    client, deck, _icons = _client(tmp_path)

    new = _VALID.replace("First", "Second")
    assert client.put("/api/deck", json={"yaml": new}).status_code == 200
    assert "Second" in deck.read_text(encoding="utf-8")

    bad = client.put("/api/deck", json={"yaml": _INVALID})
    assert bad.status_code == 400
    # The on-disk deck must be unchanged (not corrupted) by the rejected edit.
    assert "Second" in deck.read_text(encoding="utf-8")


def test_icon_upload_and_list(tmp_path: Path) -> None:
    """A .png uploads and lists; a non-png is rejected."""
    client, _deck, icons = _client(tmp_path)

    r = client.post("/api/icons", files={"file": ("hi.png", b"PNGDATA", "image/png")})
    assert r.status_code == 200 and r.json()["name"] == "hi.png"
    assert (icons / "hi.png").read_bytes() == b"PNGDATA"
    assert "hi.png" in client.get("/api/icons").json()

    bad = client.post("/api/icons", files={"file": ("x.txt", b"nope", "text/plain")})
    assert bad.status_code == 400


def test_ui_page_served(tmp_path: Path) -> None:
    """The editor SPA is served at /ui."""
    client, _deck, _icons = _client(tmp_path)
    r = client.get("/ui")
    assert r.status_code == 200 and "PrestoDeck" in r.text and "deck.yaml" in r.text
    # Import/export controls are present so decks can be backed up and loaded.
    assert 'id="import"' in r.text and 'id="export"' in r.text


def test_info_exposes_ws_port(tmp_path: Path) -> None:
    """The live preview needs the device WebSocket port to connect."""
    client, _deck, _icons = _client(tmp_path)
    assert client.get("/api/info").json()["ws_port"] == 7878


def test_icon_bytes_served_and_traversal_rejected(tmp_path: Path) -> None:
    """Icons are served by name; missing files and path traversal are refused."""
    client, _deck, icons = _client(tmp_path)
    (icons / "mic.png").write_bytes(b"PNGDATA")

    ok = client.get("/api/icons/mic.png")
    assert ok.status_code == 200 and ok.content == b"PNGDATA"

    assert client.get("/api/icons/missing.png").status_code == 404
    assert client.get("/api/icons/notes.txt").status_code == 404
    # A traversal attempt must not escape the icons directory.
    assert client.get("/api/icons/..%2f..%2fdeck.yaml").status_code == 404
