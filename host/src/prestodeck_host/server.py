"""WebSocket server for the PrestoDeck host.

Binds a ``websockets`` server to ``0.0.0.0:7878`` and accepts device
connections on the ``/deck`` path. Each connection follows this flow:

    await the device ``hello``  ->  log it (device_id, firmware, ip)
      ->  hand off to a :class:`~prestodeck_host.session.Session`
      ->  pump inbound frames, logging button presses/releases

Any inbound frame is treated as keepalive. The server also sends periodic
``ping`` frames so the device's 30s idle timeout never elapses on an idle link.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from prestodeck_host import protocol
from prestodeck_host.config import DeckConfig
from prestodeck_host.engine import ActionEngine
from prestodeck_host.icons import IconStore
from prestodeck_host.log import get_logger
from prestodeck_host.obs_feedback import ObsFeedback, bindings_from_config
from prestodeck_host.protocol import Envelope, MessageType
from prestodeck_host.session import Session
from prestodeck_host.state import StateStore

if TYPE_CHECKING:
    from websockets.asyncio.server import Server as WSServer

    from prestodeck_host.obs import ObsClient

_logger = get_logger(__name__)

DECK_PATH = "/deck"
BIND_HOST = "0.0.0.0"
PING_INTERVAL_SECONDS = 10.0


class Server:
    """Owns the WebSocket listener and the set of active device sessions."""

    def __init__(
        self,
        config: DeckConfig,
        icon_store: IconStore,
        store: StateStore | None = None,
        obs: ObsClient | None = None,
    ) -> None:
        self._config = config
        self._icon_store = icon_store
        self._engine = ActionEngine(config)
        self._store = store if store is not None else StateStore()
        self._obs = obs
        # Active sessions namespaced by device_id (multi-device fan-out).
        self._sessions: dict[str, Session] = {}
        # Bridge live OBS state onto buttons that opt into feedback.
        self._feedback: ObsFeedback | None = None
        if obs is not None:
            self._feedback = ObsFeedback(
                obs,
                lambda: bindings_from_config(self._config.pages),
                self._broadcast_button_state,
            )

    async def _broadcast_button_state(self, page: str, button: str, state: dict[str, Any]) -> None:
        """Push a ``set_button_state`` to every connected device (OBS feedback)."""
        for session in list(self._sessions.values()):
            try:
                await session.push_button_state(page, button, state)
            except Exception as exc:  # one device failing must not block others
                _logger.debug("[%s] feedback push failed: %s", session.device_id, exc)

    @property
    def port(self) -> int:
        """TCP port the server binds to."""
        return self._config.host.port

    async def apply_config(self, config: DeckConfig) -> None:
        """Hot-reload: swap in a new config and push it to every connected device."""
        self._config = config
        self._engine.set_config(config)
        _logger.info("config reloaded: %d page(s); pushing to %d device(s)",
                     len(config.pages), len(self._sessions))
        for session in list(self._sessions.values()):
            session.set_config(config)
            try:
                await session.push_config()
                await session.restore_button_states()  # replay toggle on/off state
            except Exception as exc:  # one device failing must not block others
                _logger.warning("[%s] failed to push reloaded config: %s", session.device_id, exc)
        if self._feedback is not None:
            await self._feedback.resync()  # reflect OBS state for any new bindings

    async def serve_forever(self) -> None:
        """Run the WebSocket server until cancelled."""
        async with await self.start() as server:
            await server.serve_forever()

    async def start(self) -> WSServer:
        """Bind the listener and return the running server object.

        Exposed separately from :meth:`serve_forever` so callers (and tests) can
        manage the server lifecycle and run it alongside other tasks.
        """
        server = await serve(self._handle, BIND_HOST, self.port)
        _logger.info("WebSocket server listening on ws://%s:%d%s", BIND_HOST, self.port, DECK_PATH)
        return server

    async def _handle(self, connection: ServerConnection) -> None:
        """Handle one device connection for its full lifetime."""
        path = connection.request.path if connection.request is not None else ""
        peer = self._peer_of(connection)
        if path != DECK_PATH:
            _logger.warning("rejecting connection from %s: bad path %r", peer, path)
            await connection.close(code=1008, reason="unknown path")
            return

        session = await self._handshake(connection, peer)
        if session is None:
            return

        self._sessions[session.device_id] = session
        ping_task = asyncio.create_task(self._ping_loop(connection))
        try:
            await session.start()
            if self._feedback is not None:
                await self._feedback.resync()  # sync OBS state onto the new device
            await self._pump(connection, session)
        finally:
            ping_task.cancel()
            self._sessions.pop(session.device_id, None)
            _logger.info("[%s] disconnected", session.device_id)

    async def _handshake(self, connection: ServerConnection, peer: str) -> Session | None:
        """Await and validate the device ``hello``; build a :class:`Session`.

        Returns ``None`` (after closing the connection) if the first frame is not
        a well-formed ``hello``.
        """
        try:
            raw = await connection.recv()
        except websockets.ConnectionClosed:
            _logger.info("connection from %s closed before hello", peer)
            return None

        try:
            envelope = protocol.decode(raw)
        except (ValueError, TypeError) as exc:
            _logger.warning("malformed first frame from %s: %s", peer, exc)
            await connection.close(code=1003, reason="malformed hello")
            return None

        if envelope.type is not MessageType.HELLO:
            _logger.warning("expected hello from %s, got %s", peer, envelope.type.value)
            await connection.close(code=1002, reason="expected hello")
            return None

        device_id = str(envelope.payload.get("device_id", "unknown"))
        firmware = str(envelope.payload.get("firmware", "unknown"))
        _logger.info("hello device_id=%s firmware=%s ip=%s", device_id, firmware, peer)

        async def send(message: Envelope) -> None:
            await connection.send(protocol.encode(message))

        return Session(
            device_id=device_id,
            firmware=firmware,
            peer=peer,
            send=send,
            config=self._config,
            icon_store=self._icon_store,
            engine=self._engine,
            store=self._store,
            obs=self._obs,
        )

    async def _pump(self, connection: ServerConnection, session: Session) -> None:
        """Read inbound frames until the connection closes, dispatching each."""
        try:
            async for raw in connection:
                try:
                    envelope = protocol.decode(raw)
                except (ValueError, TypeError) as exc:
                    _logger.warning("[%s] dropping malformed frame: %s", session.device_id, exc)
                    continue
                await session.handle(envelope)
        except websockets.ConnectionClosed:
            return

    async def _ping_loop(self, connection: ServerConnection) -> None:
        """Send a protocol-level ``ping`` periodically to keep the link warm."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                await connection.send(protocol.encode(protocol.make_ping()))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            return

    @staticmethod
    def _peer_of(connection: ServerConnection) -> str:
        """Return a human-readable ``ip:port`` for the remote peer."""
        remote = connection.remote_address
        if remote is None:
            return "unknown"
        host, port = remote[0], remote[1]
        return f"{host}:{port}"
