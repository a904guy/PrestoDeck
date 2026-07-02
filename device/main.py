"""PrestoDeck device entry point.

The board runs this after ``boot.py`` has brought up WiFi and constructed the
Presto. Everything happens in a single asyncio event loop. The shared runtime
state and host-message handling live in ``lib/prestodeck/app.py`` (``App``); this
module wires up the long-lived coroutines and the reconnect supervisor:

  * render tick  -- repaint the active page (plus toast/badge/page-dots) when dirty,
  * LED fader    -- ease the back LEDs toward the press/swipe target colour,
  * touch poll   -- turn touches into tap / swipe / cancel gestures,
  * connection   -- resolve the host, connect, and reconnect with backoff.

Per connected session the device sends ``hello``, awaits the host ``config``,
then pumps incoming messages (heartbeat pings alongside) until the link drops.
On any transport fault the supervisor reconnects with exponential backoff
(1/2/4/8...capped at 30s) plus +/-20% jitter, queueing presses meanwhile.

This module imports only ``asyncio`` and pure helpers at the top level so it
parses on host CPython; device-only imports are reached lazily through ``boot``.
"""

import asyncio

from lib.prestodeck import clock
from lib.prestodeck import log
from lib.prestodeck import page as page_mod
from lib.prestodeck import protocol
from lib.prestodeck.app import App
from lib.prestodeck.client import WSClient
from lib.prestodeck.input import TouchInput
from lib.prestodeck.ui import RenderSurface

DEVICE_ID = "prestodeck-01"
FIRMWARE = "presto-wireless-august-2025"
WS_PATH = "/deck"
CONFIG_WAIT_S = 3.0
HEARTBEAT_S = 10
BACKOFF_BASE_S = 1
BACKOFF_CAP_S = 30


def next_backoff(attempt, rand_fn=None):
    """Compute the backoff delay for a reconnect attempt. Pure; testable.

    Exponential 1/2/4/8... capped at 30s, with +/-20% jitter.

    :param attempt: zero-based consecutive failure count.
    :param rand_fn: callable returning a float in [0,1); injectable for tests.
    :returns: delay in seconds (float).
    """
    if rand_fn is None:
        import random
        rand_fn = random.random
    base = BACKOFF_BASE_S * (2 ** attempt)
    if base > BACKOFF_CAP_S:
        base = BACKOFF_CAP_S
    jitter = (rand_fn() * 0.4) - 0.2  # [-0.2, +0.2)
    return base * (1.0 + jitter)


async def ws_pump(app):
    """Receive host messages and dispatch them until the link drops."""
    while True:
        msg = await app.client.recv_json()
        try:
            msg_type, _mid, payload = protocol.parse_message(
                msg if isinstance(msg, str) else __import__("json").dumps(msg)
            )
        except ValueError as exc:
            log.warn("dropping malformed frame: {0}".format(exc))
            continue
        if app.apply(msg_type, payload):
            app.dirty = True


async def render_tick(app, interval_s=0.05):
    """Redraw the active page (plus any active toast overlay) and present it."""
    log.info("render loop started")
    while True:
        now = clock.ticks_ms()
        toast = app.toast_active(now)
        if (app.dirty or toast) and app.page is not None:
            app.page.draw(app.surface, app.icons)
            app.draw_page_dots(app.surface)
            if toast:
                app.draw_toast(app.surface)
            if app.reconnecting:
                app.draw_badge(app.surface)
            try:
                app.presto.update()
            except Exception as exc:
                log.warn("presto.update failed: {0}".format(exc))
            # Keep redrawing while a toast is up so it clears itself on expiry.
            app.dirty = toast
        await asyncio.sleep(interval_s)


async def heartbeat(app, period_s=HEARTBEAT_S):
    """Send a ``ping`` every ``period_s`` seconds and log free memory."""
    while True:
        await asyncio.sleep(period_s)
        try:
            import gc

            log.info("gc.mem_free={0}".format(gc.mem_free()))
        except Exception:
            pass
        if app.client is not None and app.client.connected:
            await app.client.send_json(protocol.make_ping(clock.ticks_ms()))


async def session(app, host, port):
    """Run one connected session: connect, hello, config-or-fallback, loop.

    Raises on transport fault so the supervisor can back off and reconnect.
    """
    # Until the first config has ever been applied, show the connecting screen.
    # After that, keep the existing layout across reconnects.
    if not app.has_config:
        app.set_page(page_mod.make_connecting_screen(app.ip, "Connecting to host"))

    app.client = WSClient(host, port, WS_PATH)
    await app.client.connect()

    await app.client.send_json(
        protocol.make_hello(DEVICE_ID, FIRMWARE, str(host), clock.ticks_ms())
    )

    if not app.has_config:
        app.set_page(page_mod.make_connecting_screen(app.ip, "Waiting for config"))

    # Await the first host config; applying it replaces the status screen. On
    # timeout we stay on the status screen rather than show a stale local page.
    try:
        first = await asyncio.wait_for(app.client.recv_json(), CONFIG_WAIT_S)
        msg_type, _mid, payload = protocol.parse_message(
            first if isinstance(first, str) else __import__("json").dumps(first)
        )
        app.apply(msg_type, payload)
    except Exception:
        log.warn("no host config in {0}s; staying on status screen".format(CONFIG_WAIT_S))

    # Connected: clear the reconnecting badge and replay any queued presses.
    app.set_reconnecting(False)
    await app.replay_presses()

    # ws_pump drives the session lifecycle: it runs until the link drops, then
    # raises. heartbeat is connection-bound and cancelled when ws_pump exits.
    # (Touch runs continuously at the top level so the layout stays interactive
    # while disconnected, and presses queue for replay.)
    hb_task = asyncio.create_task(heartbeat(app))
    try:
        await ws_pump(app)
    finally:
        hb_task.cancel()


async def supervisor(app, host, port):
    """Reconnect loop with exponential backoff + jitter."""
    attempt = 0
    while True:
        try:
            await session(app, host, port)
            attempt = 0  # clean exit -> reset backoff
        except Exception as exc:
            log.error("session ended: {0}".format(exc))
            # Keep the layout interactive but show the reconnecting badge.
            app.set_reconnecting(True)
            delay = next_backoff(attempt)
            attempt += 1
            log.info("reconnecting in {0:.1f}s".format(delay))
            if app.client is not None:
                await app.client.close()
            await asyncio.sleep(delay)


async def _connect_loop(app, wifi_ok):
    """Resolve the host (retrying discovery) then supervise the connection.

    Keeps the connecting screen (with the device IP) on-screen while no host can
    be found, retrying every few seconds so the device recovers on its own once
    the host reappears.
    """
    import boot

    host = None
    while host is None:
        host, port = await boot.resolve_host(wifi_ok)
        if host is None:
            if not app.has_config:
                app.set_page(page_mod.make_connecting_screen(app.ip, "Searching for host"))
            await asyncio.sleep(3)
    await supervisor(app, host, port)


async def main(presto, wifi_ok):
    """Run the render loop, LED fader, touch poll, and connection supervisor.

    WiFi and the Presto are already up (brought up synchronously before the
    loop). This resolves the host (inside the loop, async mDNS allowed) and then
    supervises the connection.

    :param presto: the live Presto object (constructed before the loop).
    :param wifi_ok: whether WiFi associated successfully.
    """
    import boot

    surface = RenderSurface(presto.display)
    app = App(presto, surface)
    app.ip = boot.device_ip()

    # Show the connecting screen (with the device IP) until the host config lands.
    app.set_page(page_mod.make_connecting_screen(app.ip, "Connecting..."))

    # Touch polls continuously (one loop, no leak) so the UI stays interactive
    # even while disconnected; presses queue and replay on reconnect.
    touch = TouchInput(app.presto, app.active_page)

    await asyncio.gather(
        render_tick(app),
        app.led_tick(),
        touch.poll(app.on_down, app.on_tap, app.on_repeat, app.on_swipe, app.on_cancel),
        _connect_loop(app, wifi_ok),
    )


def run_device():
    """Synchronous device entry point.

    Brings up WiFi and constructs the Presto BEFORE entering the asyncio loop
    (``ezwifi.connect`` would corrupt a running loop), then runs ``main``.
    """
    import boot

    ssid, password = boot.load_secrets()
    wifi_ok = boot.bring_up_wifi(ssid, password)
    presto = boot.construct_presto()
    asyncio.run(main(presto, wifi_ok))


if __name__ == "__main__":
    run_device()
