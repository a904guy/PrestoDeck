"""Server smoke test: a websockets client performs the hello->config exchange.

Runs entirely in-process with no hardware: it binds the real :class:`Server` to
an ephemeral port and connects a ``websockets`` client that sends ``hello`` and
asserts the returned resolved ``config`` frame's shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import websockets
from websockets.asyncio.client import connect

from prestodeck_host import protocol
from prestodeck_host.config import ButtonConfig, DeckConfig, PageConfig
from prestodeck_host.icons import IconStore
from prestodeck_host.protocol import Envelope, MessageType
from prestodeck_host.server import DECK_PATH, Server

if TYPE_CHECKING:
    from websockets.asyncio.server import Server as WSServer


def _make_server() -> Server:
    """Build a Server bound to an ephemeral port serving a 2x2 main page."""
    config = DeckConfig(
        version=1,
        default_page="main",
        pages=[
            PageConfig(
                id="main",
                grid=[2, 2],
                buttons=[
                    ButtonConfig(id="b1", row=0, col=0, label="One"),
                    ButtonConfig(id="b2", row=0, col=1, label="Two"),
                    ButtonConfig(id="b3", row=1, col=0, label="Three"),
                    ButtonConfig(id="b4", row=1, col=1, label="Four"),
                ],
            )
        ],
    )
    config.host.port = 0  # let the OS choose a free ephemeral port
    return Server(config, IconStore(Path("nonexistent-icons")))


def _bound_port(ws_server: WSServer) -> int:
    """Return the actual TCP port the server bound to."""
    sockets = ws_server.sockets
    assert sockets, "server has no bound sockets"
    port: int = sockets[0].getsockname()[1]
    return port


async def test_hello_to_config_exchange() -> None:
    """A client sending hello receives the resolved 2x2 config frame."""
    server = _make_server()
    ws_server = await server.start()
    try:
        port = _bound_port(ws_server)
        uri = f"ws://127.0.0.1:{port}{DECK_PATH}"
        async with connect(uri) as client:
            hello = Envelope(
                type=MessageType.HELLO,
                payload={"device_id": "test-presto", "firmware": "presto-test"},
            )
            await client.send(protocol.encode(hello))

            raw = await client.recv()
            frame = protocol.decode(raw)

        assert frame.type is MessageType.CONFIG
        assert frame.payload["default_page"] == "main"
        assert frame.payload["icons_manifest"] == []
        page = frame.payload["pages"][0]
        assert page["id"] == "main"
        assert page["grid"] == [2, 2]
        assert [b["id"] for b in page["buttons"]] == ["b1", "b2", "b3", "b4"]
        theme = frame.payload["theme"]
        assert len(theme["background"]) == 3
        assert len(theme["default_outline_color"]) == 3
    finally:
        ws_server.close()
        await ws_server.wait_closed()


async def test_bad_path_rejected() -> None:
    """A connection to a path other than /deck is closed by the server."""
    server = _make_server()
    ws_server = await server.start()
    try:
        port = _bound_port(ws_server)
        uri = f"ws://127.0.0.1:{port}/wrong"
        async with connect(uri) as client:
            with pytest.raises(websockets.ConnectionClosed):
                await client.recv()
    finally:
        ws_server.close()
        await ws_server.wait_closed()


@pytest.mark.hardware
async def test_real_presto_renders_test_page() -> None:
    """Hardware-only: a real Presto connects and renders the configured page.

    Requires a physical Presto on the LAN running the deployed firmware. Skipped
    in CI; run with ``pytest -m hardware`` against attached hardware. The
    assertion is performed visually by the operator, so the body only documents
    the manual check.
    """
    pytest.skip("requires a physical Presto on the LAN; run manually with -m hardware")
