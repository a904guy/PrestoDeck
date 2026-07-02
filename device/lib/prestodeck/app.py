"""Shared runtime state and host-message dispatch for the PrestoDeck device.

``App`` holds everything the concurrent coroutines in ``main.py`` share: the
active page and page registry, the icon cache and in-flight reassembly buffers,
the back-LED fade target, the transient toast, the disconnected press queue, and
the touch-gesture handlers (``on_down`` / ``on_tap`` / ``on_swipe`` /
``on_cancel``). It also routes decoded host messages via :meth:`App.apply` so
``main.py`` stays a thin event-loop orchestrator.

This module is import-safe on host CPython: it imports only pure sibling modules
at the top level; the device-only ``presto`` object is passed in at runtime.
"""

import asyncio

from . import clock
from . import log
from . import page as page_mod
from . import protocol
from . import ui
from .iconcache import IconCache

# Queue at most this many presses while disconnected; oldest are dropped.
_MAX_QUEUED_PRESSES = 16


class App:
    """Holds shared runtime state across the device's concurrent coroutines."""

    def __init__(self, presto, surface):
        """Bind hardware/render state.

        :param presto: the live Presto object.
        :param surface: the ``RenderSurface`` wrapping its PicoGraphics.
        """
        self.presto = presto
        self.surface = surface
        self.client = None
        self.page = None
        self.dirty = True
        # Device IP (for the connecting screen) and whether a host config has
        # ever been applied (controls connecting-screen vs keep-layout on reconnect).
        self.ip = ""
        self.has_config = False
        # Back-LED fade state: the fader coroutine eases _led_current toward
        # _led_target each tick, so a press fades the LEDs up and a release fades
        # them down, in step with the button's pressed-state fill.
        self._led_target = (0, 0, 0)
        self._led_current = (0.0, 0.0, 0.0)
        # Icon cache + in-flight reassembly buffers (name -> {seq: data_b64}) and
        # the expected sha per in-flight icon.
        self.icons = IconCache()
        self._icon_buf = {}
        self._icon_sha = {}
        # Multi-page state: all pages by id, the page order (for swipe nav), the
        # currently-highlighted button, plus the transient notify toast.
        self.pages = {}
        self.page_order = []
        self._held_button = None
        self._toast_text = None
        self._toast_color = None
        self._toast_until = 0
        # Robustness: queue presses while disconnected (oldest dropped past the
        # cap) and replay on reconnect; show a small reconnecting badge meanwhile.
        self._press_queue = []
        self._reconnecting = False

    def active_page(self):
        """Return the current page (for the touch input page_getter)."""
        return self.page

    def set_page(self, page):
        """Replace the active page, mark dirty, fade LEDs out, and reclaim memory."""
        self.page = page
        self.dirty = True
        self._led_target = (0, 0, 0)
        # Force a collection between page transitions to keep PSRAM predictable.
        try:
            import gc

            gc.collect()
        except Exception:
            pass

    # -- disconnected press queue -------------------------------------------

    def queue_press(self, page, button, ts):
        """Queue a press while disconnected (oldest dropped past the cap)."""
        self._press_queue.append((page, button, ts))
        if len(self._press_queue) > _MAX_QUEUED_PRESSES:
            self._press_queue.pop(0)
        log.info("queued press {0}/{1} (depth={2})".format(page, button, len(self._press_queue)))

    async def replay_presses(self):
        """Replay queued presses oldest-first after reconnect."""
        if not self._press_queue or self.client is None or not self.client.connected:
            return
        queued = self._press_queue
        self._press_queue = []
        log.info("replaying {0} queued press(es)".format(len(queued)))
        for page, button, ts in queued:
            await self.client.send_json(protocol.make_button_press(page, button, ts))

    # -- reconnecting badge -------------------------------------------------

    def set_reconnecting(self, value):
        """Flag the reconnecting badge on/off and request a repaint."""
        if self._reconnecting != value:
            self._reconnecting = value
            self.dirty = True

    @property
    def reconnecting(self):
        """Whether the reconnecting badge should be shown."""
        return self._reconnecting

    def draw_badge(self, surface):
        """Draw a small reconnecting badge in the top-right corner."""
        surface.rounded_rect(ui.SCREEN_W - 150, 8, 142, 30, 8, (200, 120, 0))
        surface.text_centered("reconnecting", ui.SCREEN_W - 79, 23, ui.Theme.TEXT, 2)

    # -- pages --------------------------------------------------------------

    def switch_page(self, page_id):
        """Switch to a page by id from the registry. Returns ``True`` on success."""
        page = self.pages.get(page_id)
        if page is None:
            log.warn("switch_page: unknown page {0}".format(page_id))
            return False
        self.set_page(page)
        return True

    def navigate_relative(self, step):
        """Switch ``step`` pages along the page order. Returns the new id or None."""
        if not self.page_order or self.page is None:
            return None
        try:
            i = self.page_order.index(self.page.page_id)
        except ValueError:
            return None
        j = i + step
        if 0 <= j < len(self.page_order) and self.page_order[j] != self.page.page_id:
            target = self.page_order[j]
            if self.switch_page(target):
                return target
        return None

    def draw_page_dots(self, surface):
        """Draw page indicator dots at the bottom; filled for the current page."""
        count = len(self.page_order)
        if count <= 1 or self.page is None:
            return
        try:
            current = self.page_order.index(self.page.page_id)
        except ValueError:
            current = 0
        spacing = 22
        x0 = ui.SCREEN_W // 2 - (count - 1) * spacing // 2
        y = ui.SCREEN_H - 12
        for i in range(count):
            color = ui.Theme.TEXT if i == current else (70, 70, 84)
            surface.dot(x0 + i * spacing, y, 5, color)

    # -- toast --------------------------------------------------------------

    def show_toast(self, text, duration_ms=2000, color=None):
        """Show a transient toast overlay for ``duration_ms``."""
        self._toast_text = text
        self._toast_color = tuple(color) if color else None
        self._toast_until = clock.ticks_ms() + int(duration_ms)
        self.dirty = True

    def toast_active(self, now):
        """Return whether a toast is currently visible at time ``now`` (ticks_ms)."""
        if self._toast_text is None:
            return False
        return clock.ticks_diff(self._toast_until, now) > 0

    def draw_toast(self, surface):
        """Draw the toast overlay as a band near the bottom of the screen."""
        color = self._toast_color or ui.Theme.BUTTON_OUTLINE
        h = 64
        y = ui.SCREEN_H - h - 20
        surface.rounded_rect(20, y, ui.SCREEN_W - 40, h, 16, color)
        surface.text_centered(self._toast_text, ui.SCREEN_W // 2, y + h // 2, ui.Theme.TEXT, 3)

    # -- LEDs ---------------------------------------------------------------

    async def led_tick(self, interval_ms=20, step=0.18):
        """Continuously ease the back LEDs toward the current target colour.

        Runs as a top-level coroutine: gesture handlers set ``_led_target`` and
        the LEDs fade toward it each tick, so a press fades the LEDs up and a
        release fades them down. LED faults are swallowed so they never break
        the UI.

        :param interval_ms: fade tick cadence in milliseconds.
        :param step: fraction of the remaining distance to close each tick.
        """
        num = getattr(self.presto, "NUM_LEDS", 7)
        last = None
        while True:
            tr, tg, tb = self._led_target
            cr, cg, cb = self._led_current
            cr += (tr - cr) * step
            cg += (tg - cg) * step
            cb += (tb - cb) * step
            self._led_current = (cr, cg, cb)
            rgb = (int(cr + 0.5), int(cg + 0.5), int(cb + 0.5))
            if rgb != last:
                try:
                    for i in range(num):
                        self.presto.set_led_rgb(i, rgb[0], rgb[1], rgb[2])
                except Exception as exc:
                    log.warn("LED fade failed: {0}".format(exc))
                last = rgb
            await clock.sleep_ms(interval_ms)

    def flash_leds(self, color):
        """Snap the back LEDs to ``color`` then fade out (a quick refresh flash)."""
        self._led_current = (float(color[0]), float(color[1]), float(color[2]))
        self._led_target = (0, 0, 0)

    # -- touch gesture handlers ---------------------------------------------

    async def on_down(self, button):
        """Finger landed on a button: show the pressed fill + flash the LEDs.

        This one redraw happens while the finger is still landing (before any
        swipe motion), so it does not starve the touch sampler. No further
        redraws happen until the gesture ends -- that is what keeps swipes dense.
        """
        self._held_button = button
        button.pressed = True
        self.dirty = True
        self._led_target = button.color if button.color is not None else (0, 0, 0)

    async def on_tap(self, button, held_ms):
        """A committed tap: run the button (device-local navigate or send press)."""
        if button.navigate:
            switched = self.switch_page(button.navigate)
            if switched and self.client is not None and self.client.connected:
                await self.client.send_json(protocol.make_page_changed(button.navigate))
        else:
            ts = clock.ticks_ms()
            if self.client is not None and self.client.connected:
                await self.client.send_json(
                    protocol.make_button_press(self.page.page_id, button.button_id, ts)
                )
                await self.client.send_json(
                    protocol.make_button_release(self.page.page_id, button.button_id, ts, held_ms)
                )
            else:
                # Queue while disconnected; replayed after reconnect.
                self.queue_press(self.page.page_id, button.button_id, ts)
        self._clear_held()

    async def on_repeat(self, button):
        """Auto-repeat tick for a held button: re-send the press so the host
        runs the action again (e.g. volume up/down while held)."""
        if self.page is None or self.client is None or not self.client.connected:
            return
        ts = clock.ticks_ms()
        await self.client.send_json(
            protocol.make_button_press(self.page.page_id, button.button_id, ts)
        )
        await self.client.send_json(
            protocol.make_button_release(self.page.page_id, button.button_id, ts, 0)
        )

    async def on_swipe(self, direction):
        """Horizontal swipe: switch pages instantly and flash a refresh colour."""
        if self._held_button is not None:
            self._held_button.pressed = False
            self._held_button = None
        target = self.navigate_relative(direction)  # instant switch + redraw
        if target is None:
            self._led_target = (0, 0, 0)
            self.dirty = True
            return
        self.flash_leds((100, 230, 230))  # cyan "refresh" flash on the back LEDs
        if self.client is not None and self.client.connected:
            await self.client.send_json(protocol.make_page_changed(target))

    async def on_cancel(self):
        """The touch became a drag/short swipe: clear the highlight and hint."""
        self._clear_held()

    def _clear_held(self):
        """Un-highlight the held button, request a redraw, fade LEDs out."""
        if self._held_button is not None:
            self._held_button.pressed = False
            self._held_button = None
        self.dirty = True
        self._led_target = (0, 0, 0)

    # -- icons --------------------------------------------------------------

    async def sync_icons(self, manifest):
        """Request and cache any icons in ``manifest`` not already cached.

        Icons are fetched serially: for each missing icon, send a
        ``request_icon`` and wait until the chunk assembler
        (:meth:`on_icon_chunk`) has written it, then mark the surface dirty to
        redraw with the new icon.

        :param manifest: list of ``{"name", "sha256", "size"}`` entries.
        """
        for entry in manifest:
            name = entry.get("name")
            sha = entry.get("sha256")
            if not name or self.icons.has(name, sha):
                continue
            if self.client is None or not self.client.connected:
                return
            self._icon_buf[name] = {}
            self._icon_sha[name] = sha
            log.info("requesting icon {0}".format(name))
            await self.client.send_json(protocol.make_request_icon(name))
            received = False
            for _ in range(200):  # ~20s budget per icon
                if self.icons.has(name, sha):
                    received = True
                    break
                await asyncio.sleep(0.1)
            if not received:
                log.warn("icon {0} not received in time".format(name))
            self._icon_buf.pop(name, None)
            self._icon_sha.pop(name, None)
            self.dirty = True

    def on_icon_chunk(self, payload):
        """Accumulate one ``icon_chunk``; on the final chunk, decode and cache it."""
        import binascii

        name = payload.get("name")
        buf = self._icon_buf.get(name)
        if buf is None:
            return
        total = payload.get("total", 0)
        buf[payload.get("seq", 0)] = payload.get("data_b64", "")
        if len(buf) < total:
            return
        try:
            joined = "".join(buf[i] for i in range(total))
            raw = binascii.a2b_base64(joined)
        except Exception as exc:
            log.error("icon {0} reassembly failed: {1}".format(name, exc))
            self._icon_buf.pop(name, None)
            return
        self.icons.store(name, raw, self._icon_sha.get(name, ""))
        log.info("cached icon {0} ({1} bytes)".format(name, len(raw)))
        self.dirty = True

    # -- host message dispatch ----------------------------------------------

    def apply(self, msg_type, payload):
        """Dispatch one decoded host message to runtime state.

        Handles ``config`` (rebuild the pages), page/button/LED/buzzer/notify
        updates, and icon chunks. Unknown types are ignored.

        :returns: ``True`` if the surface should be redrawn.
        """
        if msg_type == protocol.TYPE_CONFIG:
            return self._apply_config(payload)
        if msg_type == protocol.TYPE_ICON_CHUNK:
            self.on_icon_chunk(payload)
            return False
        if msg_type == protocol.TYPE_SET_PAGE:
            return self.switch_page(payload.get("page"))
        if msg_type == protocol.TYPE_SET_BUTTON_STATE:
            return self._apply_set_button_state(payload)
        if msg_type == protocol.TYPE_SET_LED:
            self._apply_set_led(payload)
            return False
        if msg_type == protocol.TYPE_SET_BUZZER:
            self._apply_set_buzzer(payload)
            return False
        if msg_type == protocol.TYPE_NOTIFY:
            log.info("notify: {0}".format(payload.get("text", "")))
            self.show_toast(
                payload.get("text", ""), payload.get("duration_ms", 2000), payload.get("color")
            )
            return True
        if msg_type == protocol.TYPE_PONG:
            return False
        log.debug("ignoring message type {0}".format(msg_type))
        return False

    def _apply_config(self, payload):
        """Rebuild all pages from a ``config`` payload and show the default page."""
        pages, default_id = page_mod.pages_from_config(payload)
        self.pages = pages
        self.page_order = [p.get("id") for p in (payload.get("pages") or [])]
        self.has_config = True
        target = default_id if default_id in pages else None
        if target is None and pages:
            target = next(iter(pages))
        if target is not None:
            self.set_page(pages[target])
        log.info("applied host config: {0} page(s), default={1}".format(len(pages), default_id))
        manifest = payload.get("icons_manifest") or []
        if manifest:
            asyncio.create_task(self.sync_icons(manifest))
        return True

    def _apply_set_button_state(self, payload):
        """Merge a ``set_button_state`` update into the target page's button.

        The update is applied to the named page (or the active page if none is
        given) even when that page is not currently visible -- so state pushed
        for an off-screen page (e.g. OBS feedback while another page is shown)
        is retained and shows correctly once the user swipes to it. A redraw is
        only requested when the change affects the page on screen.
        """
        page_id = payload.get("page")
        target = self.pages.get(page_id) if page_id else self.page
        if target is None:
            return False
        state = payload.get("state") or {}
        changed = False
        for button in target.buttons:
            if button.button_id == payload.get("button"):
                if "label" in state:
                    button.label = state["label"]
                if state.get("color") is not None:
                    button.color = tuple(state["color"])
                if "icon" in state:
                    button.icon = state["icon"]
                changed = True
                break
        # Only repaint when the mutated page is the one currently on screen.
        return changed and target is self.page

    def _apply_set_led(self, payload):
        """Drive an LED from a ``set_led`` payload ``{index, r, g, b}``."""
        try:
            self.presto.set_led_rgb(
                payload.get("index", 0), payload.get("r", 0),
                payload.get("g", 0), payload.get("b", 0),
            )
        except Exception as exc:
            log.warn("set_led failed: {0}".format(exc))

    def _apply_set_buzzer(self, payload):
        """Drive the buzzer from a ``set_buzzer`` payload ``{freq, duty}``."""
        try:
            import presto

            presto.Buzzer().set_tone(payload.get("freq", 0.0), payload.get("duty", 0.5))
        except Exception as exc:
            log.warn("set_buzzer failed: {0}".format(exc))
