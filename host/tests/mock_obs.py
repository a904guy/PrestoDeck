"""A minimal mock obs-websocket v5 server for tests.

Performs the Hello/Identify handshake (optionally requiring a password),
answers Requests with canned response data (recording what it received), and can
emit Events to the connected client -- enough to exercise the real
:class:`~prestodeck_host.obs.ObsClient` and the feedback bridge end to end.
"""

from __future__ import annotations

import json
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from prestodeck_host.obs import build_auth

_SALT = "GkL+ak-salt"
_CHALLENGE = "challenge-9000"


class MockOBS:
    """A stand-in obs-websocket server bound to an ephemeral localhost port."""

    def __init__(
        self, password: str | None = None, responses: dict[str, dict[str, Any]] | None = None
    ) -> None:
        self.password = password
        self.responses = responses or {}
        self.requests: list[tuple[str, dict[str, Any] | None]] = []
        self._clients: set[ServerConnection] = set()
        self._server: Any = None
        self.url = ""

    async def start(self) -> str:
        """Start listening; return the ``ws://`` URL to connect to."""
        self._server = await serve(self._handle, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"
        return self.url

    async def stop(self) -> None:
        """Stop the server."""
        self._server.close()
        await self._server.wait_closed()

    async def emit(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Broadcast an OBS event to every connected client."""
        frame = json.dumps(
            {"op": 5, "d": {"eventType": event_type, "eventIntent": 0, "eventData": event_data}}
        )
        for client in list(self._clients):
            await client.send(frame)

    async def _handle(self, connection: ServerConnection) -> None:
        hello: dict[str, Any] = {"obsWebSocketVersion": "5.4.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"challenge": _CHALLENGE, "salt": _SALT}
        await connection.send(json.dumps({"op": 0, "d": hello}))

        identify = json.loads(await connection.recv())
        if self.password:
            expected = build_auth(self.password, _SALT, _CHALLENGE)
            if identify["d"].get("authentication") != expected:
                await connection.close(code=4009, reason="authentication failed")
                return
        await connection.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))

        self._clients.add(connection)
        try:
            async for raw in connection:
                message = json.loads(raw)
                if message.get("op") == 6:
                    await self._respond(connection, message["d"])
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(connection)

    async def _respond(self, connection: ServerConnection, data: dict[str, Any]) -> None:
        self.requests.append((data["requestType"], data.get("requestData")))
        await connection.send(
            json.dumps(
                {
                    "op": 7,
                    "d": {
                        "requestType": data["requestType"],
                        "requestId": data["requestId"],
                        "requestStatus": {"result": True, "code": 100},
                        "responseData": self.responses.get(data["requestType"], {}),
                    },
                }
            )
        )
