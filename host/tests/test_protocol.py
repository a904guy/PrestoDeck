"""Protocol envelope and frame-constructor tests."""

from __future__ import annotations

from prestodeck_host import protocol
from prestodeck_host.protocol import Envelope, MessageType


def test_envelope_round_trip() -> None:
    """An envelope survives encode -> decode unchanged."""
    original = Envelope(
        type=MessageType.BUTTON_PRESS,
        id="abc-123",
        payload={"button_id": "b1", "page_id": "main"},
    )
    decoded = protocol.decode(protocol.encode(original))
    assert decoded == original
    assert decoded.type is MessageType.BUTTON_PRESS
    assert decoded.id == "abc-123"
    assert decoded.payload == {"button_id": "b1", "page_id": "main"}


def test_decode_accepts_bytes() -> None:
    """decode() handles both str and bytes frames."""
    raw = b'{"type": "ping", "id": null, "payload": {}}'
    decoded = protocol.decode(raw)
    assert decoded.type is MessageType.PING
    assert decoded.id is None
    assert decoded.payload == {}


def test_make_ping_shape() -> None:
    """A ping frame is a typed envelope with an empty payload."""
    ping = protocol.make_ping()
    assert ping.type is MessageType.PING
    assert ping.payload == {}


def test_host_to_device_constructors() -> None:
    """The host->device frame constructors produce well-shaped envelopes."""
    assert protocol.make_set_button_state(
        page="main", button="b1", state={"label": "On", "color": [0, 255, 0]}
    ).payload == {
        "page": "main",
        "button": "b1",
        "state": {"label": "On", "color": [0, 255, 0]},
    }
    assert protocol.make_set_led(index=2, color=(1, 2, 3)).payload == {
        "index": 2,
        "color": [1, 2, 3],
    }
    assert protocol.make_set_page(page="macros").payload == {"page": "macros"}
    assert protocol.make_notify(text="hi").payload == {"text": "hi", "duration_ms": 2000}
    assert protocol.make_notify(text="hi", duration_ms=500, color=(1, 2, 3)).payload == {
        "text": "hi",
        "duration_ms": 500,
        "color": [1, 2, 3],
    }
    assert protocol.make_icon_chunk(name="play.png", seq=0, total=2, data_b64="AA==").payload == {
        "name": "play.png",
        "seq": 0,
        "total": 2,
        "data_b64": "AA==",
    }
