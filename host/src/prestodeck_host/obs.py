"""Minimal async client for OBS Studio's built-in obs-websocket v5 protocol.

OBS Studio (28+) ships an obs-websocket server (default ``ws://localhost:4455``,
optional password). This client keeps one persistent connection to it: it does
the ``Hello`` / ``Identify`` handshake (with SHA256 authentication when a
password is set), sends requests and matches their responses by ``requestId``,
and dispatches subscribed events to registered handlers. It reconnects with
backoff, so it tolerates OBS not being running yet and recovers when it returns.

Built on the ``websockets`` dependency the host already uses -- no extra package.

Protocol reference: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import connect

from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

# obs-websocket opcodes.
_OP_HELLO = 0
_OP_IDENTIFY = 1
_OP_IDENTIFIED = 2
_OP_EVENT = 5
_OP_REQUEST = 6
_OP_REQUEST_RESPONSE = 7

# EventSubscription bitmask: Scenes(4) | Inputs(8) | Outputs(64) | SceneItems(128).
# Covers scene changes, mute changes, stream/record/replay state, and source
# visibility -- everything the state-feedback layer reflects. Excludes the
# high-volume meter/cursor streams.
EVENT_SUBSCRIPTIONS = 4 | 8 | 64 | 128

_RPC_VERSION = 1
_REQUEST_TIMEOUT_S = 10.0

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class ObsError(Exception):
    """An OBS request failed or the connection is unavailable."""


def build_auth(password: str, salt: str, challenge: str) -> str:
    """Return the obs-websocket v5 authentication string for a password.

    ``base64(sha256( base64(sha256(password + salt)) + challenge ))``.
    """
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


class ObsClient:
    """A persistent, reconnecting connection to an obs-websocket v5 server."""

    def __init__(
        self, url: str = "ws://localhost:4455", password: str | None = None
    ) -> None:
        """Configure the client (does not connect until :meth:`run` is scheduled).

        :param url: the obs-websocket URL (default ``ws://localhost:4455``).
        :param password: server password, or ``None`` if authentication is off.
        """
        self._url = url
        self._password = password
        self._ws: Any = None
        self._identified = False
        self._next_id = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._event_handlers: dict[str, list[EventHandler]] = {}
        self._connect_handlers: list[Callable[[], Awaitable[None]]] = []

    @property
    def connected(self) -> bool:
        """Whether the client is connected and past the identify handshake."""
        return self._identified

    def on_event(self, event_type: str, handler: EventHandler) -> None:
        """Register ``handler`` to be called with the ``eventData`` of ``event_type``."""
        self._event_handlers.setdefault(event_type, []).append(handler)

    def on_connect(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register ``handler`` to run each time the identify handshake completes.

        Used to (re)sync initial state after OBS (re)connects.
        """
        self._connect_handlers.append(handler)

    async def request(
        self, request_type: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one OBS request and return its ``responseData`` (``{}`` if none).

        :raises ObsError: if not connected or OBS reports the request failed.
        """
        if self._ws is None or not self._identified:
            raise ObsError("not connected to OBS")
        self._next_id += 1
        request_id = str(self._next_id)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        payload = {
            "op": _OP_REQUEST,
            "d": {"requestType": request_type, "requestId": request_id, "requestData": data or {}},
        }
        try:
            await self._ws.send(json.dumps(payload))
            response = await asyncio.wait_for(future, _REQUEST_TIMEOUT_S)
        finally:
            self._pending.pop(request_id, None)
        status = response.get("requestStatus", {})
        if not status.get("result", False):
            raise ObsError(
                f"OBS request {request_type} failed: {status.get('comment') or status.get('code')}"
            )
        return response.get("responseData") or {}

    async def run(self) -> None:
        """Connect and service the socket forever, reconnecting with backoff."""
        attempt = 0
        while True:
            try:
                await self._session()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # connection refused, dropped, handshake fail, ...
                self._identified = False
                delay = min(2 ** attempt, 30)
                attempt += 1
                _logger.debug("OBS not connected (%s); retrying in %ss", exc, delay)
                await asyncio.sleep(delay)

    async def _session(self) -> None:
        """Run one connection: connect, handshake, then pump messages.

        The read loop is started before the on-connect handlers run so those
        handlers can issue requests (e.g. state resync) and receive responses --
        otherwise a request made during connect would deadlock waiting for a
        reply the not-yet-running read loop can never deliver.
        """
        async with connect(self._url, max_size=None) as ws:
            self._ws = ws
            try:
                # Handshake reads Hello/Identified exclusively; only then start the
                # concurrent read loop, so the two never compete for frames.
                await self._handshake(ws)
                _logger.info("connected to OBS at %s", self._url)
                reader = asyncio.create_task(self._read_loop(ws))
                try:
                    for handler in self._connect_handlers:
                        await _safe(handler())
                    await reader
                finally:
                    reader.cancel()
            finally:
                self._ws = None
                self._identified = False
                self._fail_pending(ObsError("OBS connection closed"))

    async def _read_loop(self, ws: Any) -> None:
        """Dispatch inbound frames until the connection closes."""
        async for raw in ws:
            await self._dispatch(json.loads(raw))

    async def _handshake(self, ws: Any) -> None:
        """Perform the Hello -> Identify -> Identified handshake."""
        hello = json.loads(await ws.recv())
        auth_info = hello.get("d", {}).get("authentication")
        identify: dict[str, Any] = {
            "rpcVersion": _RPC_VERSION,
            "eventSubscriptions": EVENT_SUBSCRIPTIONS,
        }
        if auth_info:
            if not self._password:
                raise ObsError("OBS requires a password but none was configured")
            identify["authentication"] = build_auth(
                self._password, auth_info["salt"], auth_info["challenge"]
            )
        await ws.send(json.dumps({"op": _OP_IDENTIFY, "d": identify}))
        reply = json.loads(await ws.recv())
        if reply.get("op") != _OP_IDENTIFIED:
            raise ObsError(f"expected Identified from OBS, got op {reply.get('op')}")
        self._identified = True

    async def _dispatch(self, message: dict[str, Any]) -> None:
        """Route one decoded OBS message to a pending request or event handlers."""
        op = message.get("op")
        data = message.get("d", {})
        if op == _OP_REQUEST_RESPONSE:
            future = self._pending.get(data.get("requestId", ""))
            if future is not None and not future.done():
                future.set_result(data)
        elif op == _OP_EVENT:
            handlers = self._event_handlers.get(data.get("eventType", ""), ())
            event_data = data.get("eventData") or {}
            for handler in handlers:
                await _safe(handler(event_data))

    def _fail_pending(self, exc: Exception) -> None:
        """Reject any in-flight requests when the connection drops."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()


async def _safe(awaitable: Awaitable[None]) -> None:
    """Await ``awaitable``, logging (not raising) any exception it produces."""
    try:
        await awaitable
    except websockets.ConnectionClosed:
        raise
    except Exception as exc:
        _logger.warning("OBS handler error: %s", exc)
