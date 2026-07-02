"""Typed message constructors and parser for the PrestoDeck wire protocol.

Wire format: every message is a single JSON object framed
one-per-WebSocket-frame, shaped as::

    {"type": <str>, "id": <str|null>, "payload": <object>}

``id`` is set only when the sender expects a correlated reply.

This module is pure (no I/O): the ``client`` module owns the socket and calls
these constructors to shape outbound frames and ``parse_message`` to decode
inbound text. Keeping it pure makes the codec unit-testable off-device.

Device->host messages (5.2): hello, button_press, button_release, page_changed,
ping. Host->device messages (5.3): config, set_led, set_buzzer, notify, ping,
pong -- the device only constructs the 5.2 set here; 5.3 messages are parsed.
"""

import json

# --- Device -> host message types ---
TYPE_HELLO = "hello"
TYPE_BUTTON_PRESS = "button_press"
TYPE_BUTTON_RELEASE = "button_release"
TYPE_PAGE_CHANGED = "page_changed"
TYPE_PING = "ping"
TYPE_REQUEST_ICON = "request_icon"

# --- Host -> device message types ---
TYPE_CONFIG = "config"
TYPE_SET_LED = "set_led"
TYPE_SET_BUZZER = "set_buzzer"
TYPE_SET_BUTTON_STATE = "set_button_state"
TYPE_SET_PAGE = "set_page"
TYPE_NOTIFY = "notify"
TYPE_PONG = "pong"
TYPE_ICON_CHUNK = "icon_chunk"


def make_message(msg_type, payload=None, msg_id=None):
    """Build a canonical wire frame dict.

    :param msg_type: one of the ``TYPE_*`` constants.
    :param payload: JSON-serialisable payload (defaults to ``{}``).
    :param msg_id: optional correlation id for request/response pairing.
    :returns: a dict ready to be JSON-encoded.
    """
    return {
        "type": msg_type,
        "id": msg_id,
        "payload": payload if payload is not None else {},
    }


def encode(msg):
    """Serialise a message dict to a JSON string (one WS frame's text).

    Pure; unit-testable off-device.

    :param msg: a dict produced by ``make_message`` / ``make_*``.
    :returns: compact JSON text.
    """
    return json.dumps(msg)


def make_hello(device_id, firmware, ip, uptime_ms):
    """Construct the initial ``hello`` handshake message.

    Announces the device identity and capabilities at session start.

    :param device_id: stable identifier for this device.
    :param firmware: firmware version string (e.g. the Pimoroli build name).
    :param ip: the device's current IP address as a string.
    :param uptime_ms: milliseconds since boot.
    """
    return make_message(
        TYPE_HELLO,
        {
            "device_id": device_id,
            "firmware": firmware,
            "ip": ip,
            "uptime_ms": uptime_ms,
        },
    )


def make_button_press(page, button, ts_ms):
    """Construct a ``button_press`` event (touch-down) message.

    :param page: id of the active page.
    :param button: id of the pressed button within that page.
    :param ts_ms: event timestamp in milliseconds (monotonic).
    """
    return make_message(
        TYPE_BUTTON_PRESS,
        {"page": page, "button": button, "ts_ms": ts_ms},
    )


def make_button_release(page, button, ts_ms, held_ms):
    """Construct a ``button_release`` event (touch-up) message.

    :param page: id of the active page.
    :param button: id of the released button within that page.
    :param ts_ms: release timestamp in milliseconds (monotonic).
    :param held_ms: how long the button was held, in milliseconds.
    """
    return make_message(
        TYPE_BUTTON_RELEASE,
        {"page": page, "button": button, "ts_ms": ts_ms, "held_ms": held_ms},
    )


def make_page_changed(page):
    """Construct a ``page_changed`` notification.

    Sent when the device's active page changes (e.g. after a navigate).

    :param page: id of the now-active page.
    """
    return make_message(TYPE_PAGE_CHANGED, {"page": page})


def make_request_icon(name):
    """Construct a ``request_icon`` message asking the host for a missing icon.

    :param name: manifest name of the icon to fetch (e.g. ``play.png``).
    """
    return make_message(TYPE_REQUEST_ICON, {"name": name})


def make_ping(ts_ms=None):
    """Construct a ``ping`` heartbeat message.

    :param ts_ms: optional originate timestamp for round-trip measurement.
    """
    return make_message(TYPE_PING, {"ts_ms": ts_ms})


def parse_message(text):
    """Parse inbound frame text into a ``(type, id, payload)`` tuple.

    Pure; unit-testable off-device. Validates the envelope shape and raises
    ``ValueError`` for malformed frames so the caller can drop/log them.

    :param text: the raw JSON text of one WebSocket frame.
    :returns: tuple ``(type_str, id_or_None, payload_dict)``.
    :raises ValueError: if the text is not a valid envelope object.
    """
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        raise ValueError("frame is not valid JSON")
    if not isinstance(obj, dict):
        raise ValueError("frame is not a JSON object")
    msg_type = obj.get("type")
    if not isinstance(msg_type, str):
        raise ValueError("frame missing string 'type'")
    payload = obj.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("frame 'payload' is not an object")
    return msg_type, obj.get("id"), payload
