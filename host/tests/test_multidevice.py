"""Multi-device test: two devices on one host keep independent toggle state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prestodeck_host.config import ButtonConfig, DeckConfig, PageConfig
from prestodeck_host.icons import IconStore
from prestodeck_host.server import DECK_PATH, Server
from prestodeck_host.state import StateStore
from tests.mock_device import MockDevice


def _toggle_deck() -> DeckConfig:
    spec: dict[str, Any] = {
        "id": "mic",
        "row": 0,
        "col": 0,
        "action": {
            "type": "toggle",
            "id": "mic",
            "on": {"type": "notify", "text": "on"},
            "off": {"type": "notify", "text": "off"},
            "on_label": "On",
            "on_color": [0, 255, 0],
            "off_label": "Off",
            "off_color": [255, 0, 0],
        },
    }
    return DeckConfig(
        version=1,
        default_page="main",
        pages=[PageConfig(id="main", grid=[1, 1], buttons=[ButtonConfig.model_validate(spec)])],
    )


async def _start(config: DeckConfig, tmp_path: Path) -> tuple[str, Any]:
    config.host.port = 0
    server = Server(config, IconStore(tmp_path / "icons"), StateStore(tmp_path / "state.json"))
    ws = await server.start()
    port = ws.sockets[0].getsockname()[1]
    return f"ws://127.0.0.1:{port}{DECK_PATH}", ws


async def test_two_devices_independent_toggle_state(tmp_path: Path) -> None:
    """Toggling on one device does not affect the other; state is per-device."""
    uri, ws = await _start(_toggle_deck(), tmp_path)
    try:
        async with (
            MockDevice(uri, device_id="presto-A") as a,
            MockDevice(uri, device_id="presto-B") as b,
        ):
            # On connect each device is sent its persisted toggle state
            # (initial=off) so the button reflects reality before any press.
            assert (await a.recv_type("set_button_state"))["payload"]["state"]["label"] == "Off"
            assert (await b.recv_type("set_button_state"))["payload"]["state"]["label"] == "Off"

            await a.press("main", "mic")  # A: off -> on
            assert (await a.recv_type("set_button_state"))["payload"]["state"]["label"] == "On"

            await b.press("main", "mic")  # B: off -> on (independent)
            assert (await b.recv_type("set_button_state"))["payload"]["state"]["label"] == "On"

            await a.press("main", "mic")  # A: on -> off; B stays on
            assert (await a.recv_type("set_button_state"))["payload"]["state"]["label"] == "Off"
    finally:
        ws.close()
        await ws.wait_closed()

    store = StateStore(tmp_path / "state.json")
    assert store.get("presto-A:mic") is False  # off -> on -> off
    assert store.get("presto-B:mic") is True  # off -> on


async def test_reconnect_restores_persisted_toggle_state(tmp_path: Path) -> None:
    """A device that reconnects is re-sent its last toggle state, unprompted."""
    uri, ws = await _start(_toggle_deck(), tmp_path)
    try:
        async with MockDevice(uri, device_id="presto-A") as a:
            await a.recv_type("set_button_state")  # initial restore (off)
            await a.press("main", "mic")  # off -> on (persisted)
            assert (await a.recv_type("set_button_state"))["payload"]["state"]["label"] == "On"

        # Reconnect the same device id: it should be told it is still "On"
        # without any interaction.
        async with MockDevice(uri, device_id="presto-A") as a2:
            assert (await a2.recv_type("set_button_state"))["payload"]["state"]["label"] == "On"
    finally:
        ws.close()
        await ws.wait_closed()
