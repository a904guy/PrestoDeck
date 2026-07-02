"""Off-device tests for the PrestoDeck firmware's pure logic.

These exercise the parts of the device code that don't touch hardware: the
clock shims, reconnect backoff, the touch debouncer, page layout math, the wire
protocol codec, and the ``App`` state machine (page registry, swipe navigation,
toast lifecycle, and host-message dispatch). They run on host CPython in CI so
the firmware can't silently break between hardware sessions.
"""

import asyncio

import main
from lib.prestodeck import clock, input as input_mod, protocol
from lib.prestodeck.app import App
from lib.prestodeck.button import Button
from lib.prestodeck.input import EDGE_DOWN, EDGE_NONE, EDGE_UP, TouchDebouncer, TouchInput
from lib.prestodeck.page import Page, grid_rects


class _FakePresto:
    NUM_LEDS = 7

    def set_led_rgb(self, *_args):
        pass


def _app():
    return App(_FakePresto(), surface=None)


# -- clock --------------------------------------------------------------------


def test_clock_helpers():
    assert isinstance(clock.ticks_ms(), int)
    assert clock.ticks_diff(100, 40) == 60
    assert clock.ticks_add(100, 40) == 140


# -- backoff ------------------------------------------------------------------


def test_next_backoff_is_bounded_and_seeded():
    assert main.next_backoff(0, rand_fn=lambda: 0.5) == 1.0
    for attempt in range(12):
        delay = main.next_backoff(attempt, rand_fn=lambda: 0.5)
        assert 0 < delay <= main.BACKOFF_CAP_S * 1.2 + 1e-6


# -- touch debounce -----------------------------------------------------------


def test_debouncer_emits_edges_after_stable_window():
    deb = TouchDebouncer(debounce_ms=80)
    assert deb.update(True, 5, 5, 0)[0] == EDGE_NONE      # candidate, not yet stable
    assert deb.update(True, 5, 5, 50)[0] == EDGE_NONE     # still within window
    assert deb.update(True, 5, 5, 100)[0] == EDGE_DOWN    # stable >= 80ms -> down
    assert deb.update(False, 5, 5, 120)[0] == EDGE_NONE   # release candidate
    assert deb.update(False, 5, 5, 220)[0] == EDGE_UP     # stable release -> up


# -- page layout --------------------------------------------------------------


def test_grid_rects_are_in_bounds_and_complete():
    rects = grid_rects(2, 2, 480, 480, margin=24, gap=20)
    assert len(rects) == 4
    for x, y, w, h in rects:
        assert x >= 24 and y >= 24
        assert x + w <= 480 - 24 and y + h <= 480 - 24


# -- protocol codec -----------------------------------------------------------


def test_protocol_roundtrip():
    frame = protocol.make_button_press("main", "b1", 1234)
    msg_type, _mid, payload = protocol.parse_message(protocol.encode(frame))
    assert msg_type == protocol.TYPE_BUTTON_PRESS
    assert payload == {"page": "main", "button": "b1", "ts_ms": 1234}


# -- App state machine --------------------------------------------------------

_CONFIG = {
    "default_page": "main",
    "pages": [
        {"id": "main", "grid": [2, 2], "buttons": []},
        {"id": "tools", "grid": [2, 2], "buttons": []},
    ],
}


def test_apply_config_builds_pages_and_selects_default():
    app = _app()
    assert app.apply(protocol.TYPE_CONFIG, _CONFIG) is True
    assert set(app.pages) == {"main", "tools"}
    assert app.page.page_id == "main"
    assert app.page_order == ["main", "tools"]


def test_swipe_navigation_walks_the_page_order():
    app = _app()
    app.apply(protocol.TYPE_CONFIG, _CONFIG)
    assert app.navigate_relative(1) == "tools"
    assert app.navigate_relative(1) is None   # already on the last page
    assert app.navigate_relative(-1) == "main"
    assert app.navigate_relative(-1) is None   # already on the first page


def test_toast_lifecycle():
    app = _app()
    app.show_toast("hi", duration_ms=1000)
    now = clock.ticks_ms()
    assert app.toast_active(now) is True
    assert app.toast_active(now + 5000) is False


def test_dispatch_notify_and_unknown():
    app = _app()
    assert app.apply(protocol.TYPE_NOTIFY, {"text": "x", "duration_ms": 500}) is True
    assert app.apply("bogus-type", {}) is False


# -- hold-to-repeat -----------------------------------------------------------


class _Touch:
    def __init__(self, touched, x, y):
        self.touched, self.x, self.y = touched, x, y


class _ScriptedPresto:
    """Fake Presto whose touch reports 'down' for the first N polls, then 'up'."""

    NUM_LEDS = 7

    def __init__(self, down_polls, x, y):
        self._down_polls, self._x, self._y = down_polls, x, y
        self._i = 0
        self.touch_a = _Touch(False, 0, 0)

    def touch_poll(self):
        down = self._i < self._down_polls
        self._i += 1
        self.touch_a = _Touch(down, self._x if down else 0, self._y if down else 0)

    def set_led_rgb(self, *_a):
        pass


def test_hold_repeat_fires_and_suppresses_tap(monkeypatch):
    """Holding a repeat-enabled button still fires on_repeat, not on_tap."""
    # Shrink the delay so the test runs quickly.
    monkeypatch.setattr(input_mod, "REPEAT_DELAY_MS", 30)
    btn = Button("vol", 0, 0, 200, 200, "Vol +", repeat_ms=20)
    page = Page("main", "", [btn])

    events = {"repeat": 0, "tap": 0, "cancel": 0}

    async def on_down(_b):
        pass

    async def on_tap(_b, _held):
        events["tap"] += 1

    async def on_repeat(_b):
        events["repeat"] += 1

    async def on_swipe(_d):
        pass

    async def on_cancel():
        events["cancel"] += 1

    async def run():
        # ~250ms of holding (down) then release, sampled every 5ms.
        presto = _ScriptedPresto(down_polls=50, x=100, y=100)
        touch = TouchInput(presto, lambda: page)
        task = asyncio.create_task(
            touch.poll(on_down, on_tap, on_repeat, on_swipe, on_cancel, interval_ms=5)
        )
        await asyncio.sleep(0.45)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())

    assert events["repeat"] >= 2      # repeated several times while held
    assert events["tap"] == 0         # no extra tap once repeats fired
    assert events["cancel"] == 1      # release cleared the highlight once
