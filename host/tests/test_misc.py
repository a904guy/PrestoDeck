"""Small coverage tests: advertiser lifecycle, deck-path resolution, input backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from prestodeck_host.actions import _input
from prestodeck_host.discovery import Advertiser


async def test_advertiser_start_and_stop() -> None:
    """The Zeroconf advertiser registers and unregisters without error."""
    advertiser = Advertiser("PrestoDeckTest", 7997)
    await advertiser.start()
    await advertiser.stop()


def test_resolve_deck_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The deck path honours --config, then the env override, then the seed."""
    from prestodeck_host.__main__ import _resolve_deck_path

    # An explicit --config wins over everything.
    cli = tmp_path / "cli.yaml"
    monkeypatch.setenv("PRESTODECK_CONFIG", str(tmp_path / "env.yaml"))
    assert _resolve_deck_path(str(cli)) == cli

    # The env override is next.
    assert _resolve_deck_path(None) == tmp_path / "env.yaml"

    # No flag, no env, nothing in the cwd: a starter deck is seeded under XDG.
    monkeypatch.delenv("PRESTODECK_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    seeded = _resolve_deck_path(None)
    assert seeded == tmp_path / "xdg" / "prestodeck" / "deck.yaml"
    assert seeded.is_file()
    assert (seeded.parent / "icons" / "play.png").is_file()


def test_find_device_dir_searches_parents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """find_device_dir locates device/ from a nested cwd, and honours an explicit path."""
    from prestodeck_host.deploy import find_device_dir

    device = tmp_path / "device"
    device.mkdir()
    (device / "main.py").write_text("# firmware\n")
    nested = tmp_path / "host" / "src"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert find_device_dir(None) == device
    assert find_device_dir(str(device)) == device
    assert find_device_dir(str(tmp_path / "nope")) is None


def test_render_secrets_quotes_safely() -> None:
    """Credentials with quotes/backslashes round-trip into valid Python."""
    from prestodeck_host.setup_device import render_secrets

    body = render_secrets('my "net"', "p\\a'ss")
    namespace: dict[str, str] = {}
    exec(body, namespace)  # noqa: S102 - exercising the generated module is the point
    assert namespace["WIFI_SSID"] == 'my "net"'
    assert namespace["WIFI_PASSWORD"] == "p\\a'ss"


def test_input_backend_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRESTODECK_INPUT_BACKEND forces the backend selection."""
    monkeypatch.setenv("PRESTODECK_INPUT_BACKEND", "pynput")
    assert _input._backend() == "pynput"
    monkeypatch.setenv("PRESTODECK_INPUT_BACKEND", "uinput")
    assert _input._backend() == "uinput"


def test_parse_combo_variants() -> None:
    """parse_combo splits modifiers from the final key."""
    assert _input.parse_combo("cmd+space") == (["cmd"], "space")
    assert _input.parse_combo("a") == ([], "a")
