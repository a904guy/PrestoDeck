"""A mock PrestoDeck device for protocol/config/action tests.

Implements the device side of the protocol over a real WebSocket so tests can
drive scripted touch sequences and assert on host-side side effects and on the
frames the host pushes back.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any

from websockets.asyncio.client import connect


class MockDevice:
    """Async-context-managed mock device: connects, says hello, drives presses."""

    def __init__(self, uri: str, device_id: str = "mock", firmware: str = "mock-fw") -> None:
        self.uri = uri
        self.device_id = device_id
        self.firmware = firmware
        self.config: dict[str, Any] | None = None
        self._conn: Any = None
        self._ws: Any = None

    async def __aenter__(self) -> MockDevice:
        self._conn = connect(self.uri)
        self._ws = await self._conn.__aenter__()
        await self._send(
            {"type": "hello", "id": None,
             "payload": {"device_id": self.device_id, "firmware": self.firmware}}
        )
        self.config = await self.recv_type("config")
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._conn.__aexit__(*exc)

    async def _send(self, obj: dict[str, Any]) -> None:
        await self._ws.send(json.dumps(obj))

    async def press(self, page: str, button: str) -> None:
        """Send a button_press for ``page``/``button``."""
        await self._send(
            {"type": "button_press", "id": None,
             "payload": {"page": page, "button": button, "ts_ms": 0}}
        )

    async def release(self, page: str, button: str, held_ms: int = 100) -> None:
        """Send a button_release for ``page``/``button``."""
        await self._send(
            {"type": "button_release", "id": None,
             "payload": {"page": page, "button": button, "ts_ms": 0, "held_ms": held_ms}}
        )

    async def send_raw(self, obj: dict[str, Any]) -> None:
        """Send an arbitrary frame (for protocol edge-case tests)."""
        await self._send(obj)

    async def recv(self, timeout: float = 1.0) -> dict[str, Any]:
        """Receive and decode one frame within ``timeout`` seconds."""
        raw = await asyncio.wait_for(self._ws.recv(), timeout)
        decoded: dict[str, Any] = json.loads(raw)
        return decoded

    async def recv_type(self, mtype: str, timeout: float = 2.0) -> dict[str, Any]:
        """Receive frames until one of type ``mtype`` arrives (or assert)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                frame = await self.recv(0.5)
            except TimeoutError:
                continue
            if frame["type"] == mtype:
                return frame
        raise AssertionError(f"did not receive a {mtype!r} frame within {timeout}s")

    async def drain(self, seconds: float = 0.5) -> list[dict[str, Any]]:
        """Collect all frames received over the next ``seconds``."""
        frames: list[dict[str, Any]] = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                frames.append(await self.recv(0.3))
        return frames
