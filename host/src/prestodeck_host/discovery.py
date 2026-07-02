"""mDNS / Zeroconf service advertiser.

Advertises the host's WebSocket endpoint as ``_prestodeck._tcp.local.`` so
devices can discover it on the local network without manual configuration.
Started on server startup and unregistered on shutdown.
"""

from __future__ import annotations

import socket

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from prestodeck_host.log import get_logger

_logger = get_logger(__name__)

SERVICE_TYPE = "_prestodeck._tcp.local."


def _local_ip() -> str:
    """Best-effort discovery of this host's primary LAN IPv4 address.

    Opens a UDP socket toward a public address (no packets are sent) to learn
    which local interface the OS would route through. Falls back to loopback.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip: str = sock.getsockname()[0]
        return ip
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class Advertiser:
    """Registers and unregisters the host's mDNS service record."""

    def __init__(self, service_name: str, port: int) -> None:
        self._service_name = service_name
        self._port = port
        self._aiozc: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    def _build_info(self) -> AsyncServiceInfo:
        """Build the service info record advertised over mDNS."""
        # Instance name must be unique within the service type and end with it.
        instance = f"{self._service_name}.{SERVICE_TYPE}"
        ip = _local_ip()
        return AsyncServiceInfo(
            type_=SERVICE_TYPE,
            name=instance,
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            properties={"path": "/deck", "version": "1"},
            server=f"{socket.gethostname()}.local.",
        )

    async def start(self) -> None:
        """Register the mDNS service record."""
        aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        info = self._build_info()
        await aiozc.async_register_service(info)
        self._aiozc = aiozc
        self._info = info
        _logger.info(
            "mDNS advertising %s on port %d as %r",
            SERVICE_TYPE,
            self._port,
            self._service_name,
        )

    async def stop(self) -> None:
        """Unregister the mDNS service record and release resources."""
        if self._aiozc is not None:
            if self._info is not None:
                await self._aiozc.async_unregister_service(self._info)
            await self._aiozc.async_close()
            _logger.info("mDNS advertisement withdrawn")
        self._aiozc = None
        self._info = None
