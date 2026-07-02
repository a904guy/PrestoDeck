"""Hand-rolled RFC 6455 WebSocket CLIENT for the device->host control channel.

WHY HAND-ROLLED: the Pimoroni MicroPython build ships no WebSocket client
(only raw ``socket``/``asyncio``/``ssl``), so we use a minimal,
purpose-built RFC 6455 client as the supported path rather than vendoring a
general-purpose library. This module implements exactly the subset PrestoDeck
needs: a single text/control channel over ``asyncio.open_connection``.

Scope of the implementation:
  * Opening handshake: HTTP/1.1 ``Upgrade`` to path ``/deck`` with a random
    16-byte base64 ``Sec-WebSocket-Key``; verifies ``Sec-WebSocket-Accept``
    as base64(sha1(key + MAGIC_GUID)) per RFC 6455 section 4.2.2.
  * Frame encode: client frames are ALWAYS masked (RFC 6455 section 5.3).
    Supports text (0x1), ping (0x9), pong (0xA), close (0x8); FIN always set.
  * Frame decode: handles FIN + opcode + 7/16/64-bit payload length. Server->
    client frames are unmasked per spec, but the decoder tolerates a mask bit.
  * Async API: ``connect``, ``send_json``, ``recv_json``, ``ping``, ``close``.

The pure helpers (``make_accept_key``, ``encode_frame``, ``decode_frame``,
``build_handshake_request``, ``parse_handshake_response``) take/return only
bytes/str and are unit-testable off-device.
"""

import binascii
import hashlib
import json
import os
import struct

from . import log

# The GUID appended to the client key during the accept computation.
MAGIC_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Opcodes (RFC 6455 section 5.2).
OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def make_accept_key(client_key_b64):
    """Compute ``Sec-WebSocket-Accept`` for a given client key.

    Pure; unit-testable. Uses the RFC 6455 SHA-1 accept digest so the handshake
    validates against any standard server (the host runs the ``websockets``
    library, which computes the same value).

    :param client_key_b64: base64 ``Sec-WebSocket-Key`` (str or bytes).
    :returns: the expected base64 accept value as a ``str``.
    """
    if isinstance(client_key_b64, str):
        client_key_b64 = client_key_b64.encode()
    digest = hashlib.sha1(client_key_b64 + MAGIC_GUID).digest()
    return binascii.b2a_base64(digest).strip().decode()


def make_client_key():
    """Generate a fresh random 16-byte base64 ``Sec-WebSocket-Key``.

    :returns: the base64 key as a ``str``.
    """
    return binascii.b2a_base64(os.urandom(16)).strip().decode()


def build_handshake_request(host, port, path, client_key):
    """Build the HTTP/1.1 Upgrade request bytes for the opening handshake.

    Pure; unit-testable.

    :param host: server host (for the Host header).
    :param port: server port (omitted from Host header when default).
    :param path: request-URI path (e.g. ``/deck``).
    :param client_key: base64 ``Sec-WebSocket-Key`` value.
    :returns: the full request as ``bytes``.
    """
    host_hdr = host if port in (80, 443) else "{0}:{1}".format(host, port)
    lines = [
        "GET {0} HTTP/1.1".format(path),
        "Host: {0}".format(host_hdr),
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: {0}".format(client_key),
        "Sec-WebSocket-Version: 13",
        "",
        "",
    ]
    return "\r\n".join(lines).encode()


def parse_handshake_response(header_bytes):
    """Parse the server's handshake response headers.

    Pure; unit-testable.

    :param header_bytes: the response up to and including the blank line.
    :returns: tuple ``(status_code:int, headers:dict)`` with lowercased keys.
    :raises ValueError: if the status line is malformed.
    """
    if isinstance(header_bytes, (bytes, bytearray)):
        text = bytes(header_bytes).decode("utf-8")
    else:
        text = header_bytes
    parts = text.split("\r\n")
    bits = parts[0].split(" ", 2)
    if len(bits) < 2 or not bits[1].isdigit():
        raise ValueError("malformed status line: " + parts[0])
    status = int(bits[1])
    headers = {}
    for line in parts[1:]:
        if line and ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status, headers


def encode_frame(opcode, payload, mask_bytes=None):
    """Encode one masked client frame (FIN=1).

    Pure; unit-testable. Client frames MUST be masked (RFC 6455 5.3).

    :param opcode: one of the ``OP_*`` constants.
    :param payload: ``bytes``/``str`` payload (may be empty).
    :param mask_bytes: 4-byte masking key; random if ``None``.
    :returns: the framed bytes ready for the wire.
    """
    if payload is None:
        payload = b""
    if isinstance(payload, str):
        payload = payload.encode()
    if mask_bytes is None:
        mask_bytes = os.urandom(4)
    n = len(payload)
    out = bytearray()
    out.append(0x80 | (opcode & 0x0F))  # FIN + opcode
    if n < 126:
        out.append(0x80 | n)  # MASK bit + 7-bit length
    elif n < 65536:
        out.append(0x80 | 126)
        out.extend(struct.pack(">H", n))
    else:
        out.append(0x80 | 127)
        out.extend(struct.pack(">Q", n))
    out.extend(mask_bytes)
    masked = bytearray(n)
    for i in range(n):
        masked[i] = payload[i] ^ mask_bytes[i & 3]
    out.extend(masked)
    return bytes(out)


def decode_frame(buf):
    """Decode one frame from the front of a buffer, if fully present.

    Pure; unit-testable. Tolerates (and unmasks) a set mask bit even though
    server->client frames should be unmasked.

    :param buf: ``bytes``/``bytearray`` containing zero or more frames.
    :returns: tuple ``(fin:bool, opcode:int, payload:bytes, consumed:int)`` or
        ``None`` if the buffer does not yet hold a complete frame.
    """
    if len(buf) < 2:
        return None
    b0 = buf[0]
    b1 = buf[1]
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    idx = 2
    if length == 126:
        if len(buf) < idx + 2:
            return None
        length = struct.unpack(">H", buf[idx:idx + 2])[0]
        idx += 2
    elif length == 127:
        if len(buf) < idx + 8:
            return None
        length = struct.unpack(">Q", buf[idx:idx + 8])[0]
        idx += 8
    mask_key = None
    if masked:
        if len(buf) < idx + 4:
            return None
        mask_key = buf[idx:idx + 4]
        idx += 4
    if len(buf) < idx + length:
        return None
    payload = bytes(buf[idx:idx + length])
    if masked:
        payload = bytes(payload[i] ^ mask_key[i & 3] for i in range(length))
    return fin, opcode, payload, idx + length


class WSClient:
    """Asyncio RFC 6455 WebSocket client over a raw TCP stream.

    Owns the socket lifecycle, performs the opening handshake, frames/deframes
    per RFC 6455, and exposes JSON send/recv plus ping/close. Control frames
    (ping/pong/close) are handled inside ``recv_json`` so callers only see
    application messages.
    """

    def __init__(self, host, port, path="/deck"):
        """Capture connection parameters; no I/O happens here.

        :param host: host IP/name resolved via discovery or config override.
        :param port: TCP port of the host WebSocket server.
        :param path: request-URI path for the WebSocket upgrade (``/deck``).
        """
        self.host = host
        self.port = port
        self.path = path
        self._reader = None
        self._writer = None
        self._buf = bytearray()
        self._connected = False

    async def connect(self):
        """Open the TCP connection and perform the opening handshake.

        Imports ``asyncio`` lazily so the module parses on host CPython without
        side effects at import time.

        :raises OSError: on socket failure.
        :raises ValueError: if the handshake is rejected or the accept key
            does not match.
        """
        import asyncio

        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        client_key = make_client_key()
        self._writer.write(build_handshake_request(self.host, self.port, self.path, client_key))
        await self._writer.drain()

        header = bytearray()
        while b"\r\n\r\n" not in header:
            chunk = await self._reader.read(256)
            if not chunk:
                raise ValueError("connection closed during handshake")
            header.extend(chunk)
        head, _sep, rest = bytes(header).partition(b"\r\n\r\n")
        status, headers = parse_handshake_response(head + b"\r\n")
        if status != 101:
            raise ValueError("handshake rejected, status " + str(status))
        if headers.get("sec-websocket-accept") != make_accept_key(client_key):
            raise ValueError("Sec-WebSocket-Accept mismatch")
        if rest:
            self._buf.extend(rest)
        self._connected = True
        log.info("WS connected to {0}:{1}{2}".format(self.host, self.port, self.path))

    async def _read_frame(self):
        """Read and return one decoded frame ``(fin, opcode, payload)``.

        Buffers partial reads until a full frame is available.
        """
        while True:
            decoded = decode_frame(self._buf)
            if decoded is not None:
                fin, opcode, payload, consumed = decoded
                # MicroPython bytearray has no slice deletion; reassign instead.
                self._buf = self._buf[consumed:]
                return fin, opcode, payload
            chunk = await self._reader.read(512)
            if not chunk:
                self._connected = False
                raise OSError("connection closed")
            self._buf.extend(chunk)

    async def _send_frame(self, opcode, payload):
        """Mask-encode and write a single frame, then drain."""
        self._writer.write(encode_frame(opcode, payload))
        await self._writer.drain()

    async def send_json(self, obj):
        """Serialise ``obj`` to JSON and send it as a masked text frame.

        :param obj: a dict shaped by the ``protocol`` module.
        """
        await self._send_frame(OP_TEXT, json.dumps(obj).encode())

    async def recv_json(self):
        """Receive the next application message as a decoded dict.

        Transparently answers ping with pong and raises ``OSError`` on close.

        :returns: the decoded JSON object (dict).
        """
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == OP_TEXT or opcode == OP_CONT:
                return json.loads(payload.decode())
            if opcode == OP_PING:
                await self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                self._connected = False
                raise OSError("server sent close")
            # Unknown/binary opcode: ignore and keep reading.

    async def ping(self, data=b""):
        """Send a WebSocket-level ping control frame.

        :param data: optional application data echoed back in the pong.
        """
        await self._send_frame(OP_PING, data)

    async def close(self, code=1000):
        """Send a close frame and tear down the stream.

        :param code: RFC 6455 close status code (default 1000 normal).
        """
        try:
            await self._send_frame(OP_CLOSE, struct.pack(">H", code))
        except OSError:
            pass
        self._connected = False
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass

    @property
    def connected(self):
        """Return whether the client currently holds an open WS connection."""
        return self._connected
