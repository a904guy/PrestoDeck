# PrestoDeck - Device Firmware

This subtree is the **on-device** runtime for PrestoDeck: the MicroPython code
that runs on a **Pimoroni Presto** (RP2350B, MicroPython v1.26 Pimoroni build).
It is the WebSocket **client**; the host runs the server. This code does **not**
run on host CPython at full capacity - it targets device-frozen modules
(`presto`, `touch`, `ezwifi`, `picographics`, `picovector`, `pngdec`, `jpegdec`)
- but it is written to *import* on CPython so its pure logic can be unit-tested
off-device (see `device/tests/`).

## Module map

```
device/
├── main.py                   # event loop: render + LED fade + touch poll + connection supervisor
├── boot.py                   # startup: WiFi (ezwifi) -> mDNS discovery, BEFORE Presto()
├── secrets.py.example        # WiFi credential template (or just run `prestodeck-setup`)
├── config.local.json.example # optional host/port override template
├── conftest.py / tests/      # off-device tests for the pure logic
└── lib/prestodeck/
    ├── __init__.py           # package marker + version
    ├── app.py                # shared runtime state + host-message dispatch (the App class)
    ├── client.py             # async WebSocket client (hand-rolled RFC 6455)
    ├── clock.py              # ticks/sleep shims that work on MicroPython and CPython
    ├── discovery.py          # mDNS scan for _prestodeck._tcp.local.
    ├── protocol.py           # typed JSON message constructors/parsers
    ├── ui.py                 # picographics render surface + theme
    ├── button.py             # button model + draw + hit-test
    ├── page.py               # page model, layout math, connecting/status screens
    ├── input.py              # touch sampling + tap/swipe gesture recognition
    ├── iconcache.py          # /icons filesystem cache + sha256 sidecars
    └── log.py                # leveled logging (the only sanctioned output sink)
```

`main.py` is intentionally thin: it wires up the long-lived coroutines and the
reconnect supervisor. All the shared state and the host-message handling live in
`lib/prestodeck/app.py` (`App`).

## Setup and deploy

The easy path is `prestodeck-setup` (from the host package): it puts your WiFi
credentials and this firmware tree onto a USB-connected Presto and resets it.

To deploy firmware changes by hand, use [`mpremote`](https://docs.micropython.org/en/latest/reference/mpremote.html):

```bash
prestodeck-deploy --reset   # autodetect the Presto, copy device/, reset
```

## Boot lifecycle

1. `boot.py` loads WiFi credentials from `secrets.py` and brings the network up
   via `ezwifi`.
2. **Only then** does it construct `Presto()` - `ezwifi.connect` runs its own
   event loop internally, so WiFi must come up before the display and before the
   asyncio loop is entered. This ordering is deliberate.
3. The host is resolved inside the loop: a `config.local.json` `host` override
   wins; otherwise an mDNS PTR query for `_prestodeck._tcp.local.` finds it.

## Input

A tap on a button runs that button's action (page switches happen on-device).
A horizontal **swipe** moves between pages; page-indicator dots show at the
bottom. The touch loop deliberately fires no callback mid-gesture, so a redraw
never starves the sampler and fast swipes still register.

## Configuration

- **`secrets.py`** - WiFi credentials. Easiest: run `prestodeck-setup`. By hand:
  copy `secrets.py.example` to `secrets.py` and fill `WIFI_SSID` /
  `WIFI_PASSWORD`. `secrets.py` is gitignored; never commit it.
- **`config.local.json`** - optional. Copy `config.local.json.example` and set
  `host` (string, or `null` for mDNS discovery) and `port` (default `7878`).
  JSON has no comments, so guidance lives here.

## Logging

No module calls `print` directly. All output goes through `log.py`
(`debug` / `info` / `warn` / `error`), the single place permitted to use the
built-in `print` as its sink.
