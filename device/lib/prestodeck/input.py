"""Touch polling, debounce, and button mapping for PrestoDeck.

Polls touch via the Presto object (``presto.touch_poll()`` then read
``presto.touch_a``), debounces transitions (default 80ms), maps the touch point
to the active page's button, and emits press (on debounced touch-down) and
release (on debounced touch-up) callbacks carrying the resolved ``Button``.

The debounce state machine (``TouchDebouncer``) is pure and host-testable: it
takes ``(is_down, x, y, now_ms)`` samples and returns discrete edge events. The
``TouchInput`` async loop only supplies real samples from hardware.
"""

from . import clock
from . import log

EDGE_NONE = 0
EDGE_DOWN = 1
EDGE_UP = 2


class TouchDebouncer:
    """Pure debounced edge detector over raw touch samples.

    Accepts a transition only after the new raw state has been stable for at
    least ``debounce_ms``. Reports DOWN/UP edges with the coordinates captured
    at the moment the edge is confirmed.
    """

    def __init__(self, debounce_ms=80):
        """Configure the stability window.

        :param debounce_ms: minimum stable interval to accept a transition.
        """
        self.debounce_ms = debounce_ms
        self._stable = False        # last accepted (debounced) state
        self._candidate = False     # last raw state seen
        self._since_ms = 0          # when candidate was first seen
        self._x = 0
        self._y = 0

    def update(self, is_down, x, y, now_ms):
        """Feed one raw sample; return an edge event. Pure.

        :param is_down: raw touch-present boolean for this sample.
        :param x: raw touch x.
        :param y: raw touch y.
        :param now_ms: monotonic time of this sample, in ms.
        :returns: tuple ``(edge, x, y)`` where edge is EDGE_NONE/DOWN/UP. The
            coordinates are the latest sampled point.
        """
        if is_down != self._candidate:
            # Raw state changed: restart the stability timer.
            self._candidate = is_down
            self._since_ms = now_ms
        self._x = x
        self._y = y
        if self._candidate != self._stable:
            if (now_ms - self._since_ms) >= self.debounce_ms:
                self._stable = self._candidate
                return (EDGE_DOWN if self._stable else EDGE_UP), x, y
        return EDGE_NONE, x, y


# Gesture thresholds, in pixels on the 480x480 panel.
SWIPE_MIN = 55   # peak horizontal travel needed to COMMIT a page swipe
TAP_SLOP = 22    # movement under this still counts as a tap (not a drag)
MIN_TAP_MS = 40  # ignore sub-40ms blips as contact bounce
_RELEASE_SAMPLES = 2  # confirm a release over 2 samples (rides over touch dropouts)
REPEAT_DELAY_MS = 350  # hold this long (still) before auto-repeat starts firing


class TouchInput:
    """Hardware touch reader that distinguishes taps from horizontal swipes.

    Bound to the live Presto object; resolves the touch start against the active
    page supplied by ``page_getter`` and dispatches gesture callbacks:

    * ``on_down(button)`` -- finger landed on a button (highlight it),
    * ``on_tap(button, held_ms)`` -- lifted without moving (commit the press),
    * ``on_repeat(button)`` -- the button has been held still past the repeat
      delay; fires every ``button.repeat_ms`` for auto-repeat (e.g. volume),
    * ``on_swipe(direction)`` -- swipe committed; ``direction`` is +1 (left,
      next page) or -1 (right, previous page),
    * ``on_cancel()`` -- the touch became a drag/short swipe, or was consumed by
      auto-repeat (clear the highlight).

    No callback fires while the finger is moving, so nothing triggers a page
    redraw mid-gesture: the (blocking) framebuffer flush never starves this loop
    and swipes stay densely sampled. Detection uses the PEAK horizontal travel
    reached during the touch (not the release position), and confirms releases
    over a couple of samples, so fast swipes and momentary touch dropouts still
    register.
    """

    def __init__(self, presto, page_getter):
        """Bind to hardware and the active-page accessor."""
        self.presto = presto
        self.page_getter = page_getter

    def _sample(self):
        """Read one raw ``(is_down, x, y)`` from the Presto. Hardware-touching.

        ``presto.touch_a`` is always a ``touch(x, y, touched)`` object (never
        ``None``); the ``touched`` flag is the authoritative down/up signal.
        """
        self.presto.touch_poll()
        point = self.presto.touch_a
        if not getattr(point, "touched", False):
            return False, 0, 0
        return True, int(point.x), int(point.y)

    async def poll(self, on_down, on_tap, on_repeat, on_swipe, on_cancel, interval_ms=20):
        """Track each touch from start to release and dispatch its gesture.

        Critically, the only callback that fires mid-touch is ``on_repeat`` (for
        held repeat-enabled buttons), and like ``on_down`` it must NOT trigger a
        page redraw -- it only sends a frame. Nothing here repaints mid-gesture,
        so the (blocking) framebuffer flush never starves this loop and swipes
        stay densely sampled.
        """
        log.info("touch poll loop started")
        active = False
        sx = sy = 0
        start_btn = None
        down_ms = 0
        moved = False
        peak_dx = 0
        release_count = 0
        repeated = False
        next_repeat_at = None
        while True:
            now = clock.ticks_ms()
            is_down, x, y = self._sample()
            if is_down:
                release_count = 0
                if not active:
                    active = True
                    sx, sy = x, y
                    moved = False
                    peak_dx = 0
                    down_ms = now
                    repeated = False
                    next_repeat_at = None
                    page = self.page_getter()
                    start_btn = page.button_at(x, y) if page is not None else None
                    if start_btn is not None:
                        await on_down(start_btn)
                else:
                    dx, dy = x - sx, y - sy
                    if abs(dx) > abs(peak_dx):
                        peak_dx = dx
                    if not moved and (abs(dx) > TAP_SLOP or abs(dy) > TAP_SLOP):
                        moved = True
                    # Auto-repeat: a still finger on a repeat-enabled button
                    # re-fires its action every repeat_ms after an initial delay.
                    repeat_ms = getattr(start_btn, "repeat_ms", None) if start_btn else None
                    if repeat_ms and not moved:
                        if next_repeat_at is None:
                            next_repeat_at = clock.ticks_add(down_ms, REPEAT_DELAY_MS)
                        if clock.ticks_diff(now, next_repeat_at) >= 0:
                            await on_repeat(start_btn)
                            repeated = True
                            next_repeat_at = clock.ticks_add(now, repeat_ms)
            elif active:
                release_count += 1
                if release_count >= _RELEASE_SAMPLES:
                    active = False
                    held = now - down_ms
                    if abs(peak_dx) >= SWIPE_MIN:
                        await on_swipe(1 if peak_dx < 0 else -1)
                    elif repeated:
                        # Repeats already fired the action; just clear the highlight.
                        await on_cancel()
                    elif not moved and start_btn is not None and held >= MIN_TAP_MS:
                        await on_tap(start_btn, held)
                    else:
                        await on_cancel()
                    start_btn = None
            await clock.sleep_ms(interval_ms)
