# PrestoDeck Wire Protocol

Transport is a WebSocket over TCP. The host runs the **server** on port 7878 at
path `/deck`; the device is the **client**. All messages are JSON, one message
per WebSocket frame.

The device has no WebSocket library in its MicroPython build, so it uses a
hand-rolled minimal RFC 6455 client (standard SHA-1 `Sec-WebSocket-Accept`), and
discovers the host via an mDNS PTR query for `_prestodeck._tcp.local.`.

## Frame envelope

```json
{"type": "string", "id": "uuid-or-null", "payload": {}}
```

`id` is set only when the sender expects a correlated reply.

## Device -> host messages

| `type` | `payload` | When |
| --- | --- | --- |
| `hello` | `{"device_id", "firmware", "ip", "uptime_ms"}` | Immediately after WS connect. |
| `button_press` | `{"page", "button", "ts_ms"}` | On touch down, after debounce. |
| `button_release` | `{"page", "button", "ts_ms", "held_ms"}` | On touch up. |
| `page_changed` | `{"page"}` | After local page navigation. |
| `request_icon` | `{"name"}` | Device asks for a missing icon. |
| `ping` | `{"ts_ms"}` | Keepalive when no other traffic for 10s. |

## Host -> device messages

| `type` | `payload` | When |
| --- | --- | --- |
| `config` | `{"version", "default_page", "theme", "pages": [...], "icons_manifest": [{"name","sha256","size"}]}` | After `hello` and after each config reload. |
| `icon_chunk` | `{"name", "seq", "total", "data_b64"}` | Streamed in response to `request_icon`. |
| `set_button_state` | `{"page", "button", "state": {"label"?, "icon"?, "color"?, "enabled"?, "badge"?}}` | Runtime button update (e.g. toggle). |
| `set_led` | `{"index", "r", "g", "b"}` | Runtime LED control. |
| `set_page` | `{"page"}` | Force navigation. |
| `notify` | `{"text", "duration_ms", "color"?}` | Transient toast. |
| `ping` | `{}` | Keepalive request. |

Each resolved `config` page is `{"id", "grid": [rows, cols], "buttons": [...]}`;
each button carries display-only fields `{"id", "row", "col", "label", "color",
"icon"}` plus an optional `"navigate"` target (navigation is device-local).
Actions stay on the host.

## Connection lifecycle

```
Device boot
  -> ezwifi.connect()  (synchronous, before the asyncio loop)
  -> mDNS scan for _prestodeck._tcp.local. (or config.local.json override)
  -> open ws://<host>:7878/deck, send hello
  -> receive config; diff icons_manifest vs the local /icons cache
  -> for each missing icon: request_icon -> host streams icon_chunk until total
  -> render default_page; enter the event loop (WS pump, touch poll, heartbeat,
     render tick, LED fader)
```

## Heartbeat and reconnect

- The device sends `ping` every 10s if no other traffic occurred.
- If no frame is received from the host for 30s, the device reconnects.
- Reconnect uses exponential backoff 1/2/4/8...capped at 30s, with +/-20% jitter.
- While disconnected the device queues up to 16 button events and replays them
  (oldest first, with their original `ts_ms`) after reconnecting, and shows a
  small "reconnecting" badge while keeping the layout interactive.
