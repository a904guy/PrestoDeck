"""Direct tests of Session.handle() across message types, and icon streaming."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prestodeck_host.config import ButtonConfig, DeckConfig, PageConfig
from prestodeck_host.engine import ActionEngine
from prestodeck_host.icons import IconStore
from prestodeck_host.protocol import Envelope, MessageType
from prestodeck_host.session import Session
from prestodeck_host.state import StateStore


def _session(tmp_path: Path, send: Any, icons: Path | None = None) -> Session:
    config = DeckConfig(
        version=1,
        default_page="main",
        pages=[
            PageConfig(
                id="main",
                grid=[1, 1],
                buttons=[
                    ButtonConfig.model_validate(
                        {"id": "b1", "row": 0, "col": 0,
                         "action": {"type": "notify", "text": "hi"}}
                    )
                ],
            )
        ],
    )
    return Session(
        device_id="dev",
        firmware="fw",
        peer="1.2.3.4:5",
        send=send,
        config=config,
        icon_store=IconStore(icons or tmp_path / "icons"),
        engine=ActionEngine(config),
        store=StateStore(tmp_path / "state.json"),
    )


async def test_button_press_dispatches_action(tmp_path: Path) -> None:
    """A button_press runs the configured action (notify -> notify frame)."""
    frames: list[Envelope] = []

    async def send(f: Envelope) -> None:
        frames.append(f)

    session = _session(tmp_path, send)
    await session.handle(
        Envelope(type=MessageType.BUTTON_PRESS, payload={"page": "main", "button": "b1"})
    )
    assert any(f.type is MessageType.NOTIFY for f in frames)


async def test_handles_release_pagechanged_pong_and_start(tmp_path: Path) -> None:
    """Release, page_changed, pong, and start() are all handled without error."""
    frames: list[Envelope] = []

    async def send(f: Envelope) -> None:
        frames.append(f)

    session = _session(tmp_path, send)
    await session.handle(
        Envelope(
            type=MessageType.BUTTON_RELEASE,
            payload={"page": "main", "button": "b1", "held_ms": 50},
        )
    )
    await session.handle(Envelope(type=MessageType.PAGE_CHANGED, payload={"page": "tools"}))
    await session.handle(Envelope(type=MessageType.PONG, payload={}))
    await session.start()
    assert any(f.type is MessageType.CONFIG for f in frames)
    assert session.device_id == "dev" and session.peer == "1.2.3.4:5"


async def test_request_icon_streams_chunks(tmp_path: Path) -> None:
    """request_icon streams icon_chunk frames; an unknown icon is a no-op."""
    icons = tmp_path / "icons"
    icons.mkdir()
    (icons / "x.png").write_bytes(b"PNGDATA" * 100)
    frames: list[Envelope] = []

    async def send(f: Envelope) -> None:
        frames.append(f)

    session = _session(tmp_path, send, icons=icons)
    await session.handle(Envelope(type=MessageType.REQUEST_ICON, payload={"name": "x.png"}))
    chunks = [f for f in frames if f.type is MessageType.ICON_CHUNK]
    assert chunks and chunks[0].payload["name"] == "x.png"

    frames.clear()
    await session.handle(Envelope(type=MessageType.REQUEST_ICON, payload={"name": "missing.png"}))
    assert not frames  # unknown icon -> nothing streamed, no crash
