"""PrestoDeck boot script.

Runs once at device startup, before ``main.py``. Establishes the network so the
main loop can assume connectivity. The startup order is strict:

  1. Bring up WiFi via ``ezwifi.connect`` using ``secrets.py`` credentials.
  2. ONLY THEN construct the ``Presto()`` display object.
  3. Resolve the host: a ``config.local.json`` override wins; else mDNS scan.

WiFi bringup is SYNCHRONOUS and MUST happen before ``asyncio.run`` is entered:
``ezwifi.connect`` drives its own event loop internally, which would clobber an
already-running loop's current task and break async sockets afterwards. So
``bring_up_wifi`` and ``construct_presto`` are called at top level (no loop), and
only host resolution (which uses async mDNS sockets) runs inside the loop via
``resolve_host``.

This module is import-safe on host CPython: device-frozen imports (``ezwifi``,
``presto``) are performed lazily inside functions, and nothing runs at import
time. ``main.py`` orchestrates the calls on the device.
"""

import json

from lib.prestodeck import log

# Firmware build name reported in the hello message.
FIRMWARE = "presto-wireless-august-2025"


def load_secrets():
    """Load WiFi credentials from the gitignored ``secrets.py``.

    :returns: tuple ``(ssid, password)``; values may be empty until populated.
    """
    try:
        import secrets
    except ImportError:
        log.error("secrets.py missing; copy secrets.py.example and fill creds")
        return "", ""
    return getattr(secrets, "WIFI_SSID", ""), getattr(secrets, "WIFI_PASSWORD", "")


def load_config():
    """Load optional host overrides from ``config.local.json``.

    :returns: dict like ``{"host": ..., "port": ...}`` (empty if absent).
    """
    try:
        with open("config.local.json") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def bring_up_wifi(ssid, password):
    """Bring up WiFi via ``ezwifi``, SYNCHRONOUSLY, before any asyncio loop.

    Must NOT be called from inside a running event loop: ``ezwifi.connect``
    runs its own loop internally and would corrupt the caller's current task.

    :param ssid: network SSID from secrets.
    :param password: network password from secrets.
    :returns: ``True`` on success, ``False`` otherwise.
    """
    if not ssid:
        log.error("WIFI_SSID is empty in secrets.py; cannot connect")
        return False
    import time

    import ezwifi
    import network

    log.info("connecting WiFi SSID={0}".format(ssid))
    try:
        # ezwifi.connect is synchronous and returns a bool; it starts association
        # but may return before the link is fully up, so we poll isconnected.
        ezwifi.connect(ssid=ssid, password=password)
    except Exception as exc:  # surface any bringup fault, keep booting
        log.error("WiFi connect failed: {0}".format(exc))
        return False

    wlan = network.WLAN(network.STA_IF)
    for _ in range(20):
        if wlan.isconnected():
            log.info("WiFi connected ip={0}".format(wlan.ifconfig()[0]))
            return True
        time.sleep(0.5)
    log.error("WiFi did not associate within timeout")
    return False


def device_ip():
    """Return the station IP address as a string, or "" if not connected."""
    import network

    wlan = network.WLAN(network.STA_IF)
    try:
        if wlan.isconnected():
            return wlan.ifconfig()[0]
    except OSError:
        pass
    return ""


def construct_presto():
    """Construct the Presto display AFTER WiFi is up (device-only, lazy).

    :returns: the constructed ``presto.Presto`` instance.
    """
    import presto

    # full_res=True selects the 480x480 DISPLAY_PRESTO_FULL_RES surface.
    device = presto.Presto(full_res=True)
    log.info("Presto constructed")
    return device


async def resolve_host(wifi_ok):
    """Resolve the host address, running inside the asyncio loop.

    A ``config.local.json`` override wins; otherwise an mDNS scan is attempted
    when WiFi is up. mDNS uses async sockets, so this must run inside the loop
    (after WiFi has been brought up synchronously by :func:`bring_up_wifi`).

    :param wifi_ok: whether WiFi associated successfully.
    :returns: tuple ``(host, port)``; ``host`` may be ``None`` if unresolved.
    """
    cfg = load_config()
    host = cfg.get("host")
    port = cfg.get("port", 7878)
    if host:
        log.info("using config.local.json host {0}:{1}".format(host, port))
        return host, port
    if wifi_ok:
        from lib.prestodeck import discovery

        info = await discovery.resolve_first()
        if info is not None:
            return info.host, info.port
    return None, port
