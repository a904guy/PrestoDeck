"""Wire protocol types for host/device communication.

All messages are JSON, one message per WebSocket frame, wrapped in a common
envelope ``{"type", "id", "payload"}``. ``id`` is set only
when the sender expects a correlated reply.

This module centralizes:

* the :class:`Envelope` model and :func:`encode` / :func:`decode` helpers, and
* typed constructors for the host -> device frames the host sends (``config``,
  ``ping``) plus the additional host -> device frames defined by the protocol
  (``set_button_state``, ``set_led``, ``set_page``, ``notify``, ``request_icon``)
  which return correctly-shaped envelopes and gain richer payload
  validation in later sprints.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """Catalog of protocol message types.

    Values are stable wire identifiers.
    """

    # device -> host
    HELLO = "hello"
    BUTTON_PRESS = "button_press"
    BUTTON_RELEASE = "button_release"
    PAGE_CHANGED = "page_changed"
    PONG = "pong"
    REQUEST_ICON = "request_icon"  # device asks for a missing icon

    # host -> device
    CONFIG = "config"
    PING = "ping"
    SET_BUTTON_STATE = "set_button_state"
    SET_LED = "set_led"
    SET_PAGE = "set_page"
    NOTIFY = "notify"
    ICON_CHUNK = "icon_chunk"

    # bidirectional / either direction
    ERROR = "error"


# An RGB triplet, e.g. ``[16, 16, 16]``.
RGB = tuple[int, int, int]


class Envelope(BaseModel):
    """Common frame envelope shared by every protocol message.

    ``id`` is set only when the sender expects a correlated reply.
    """

    type: MessageType
    id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def encode(envelope: Envelope) -> str:
    """Serialize an :class:`Envelope` to a JSON string for one WebSocket frame."""
    return envelope.model_dump_json()


def decode(raw: str | bytes) -> Envelope:
    """Parse one inbound WebSocket frame into an :class:`Envelope`.

    Raises :class:`pydantic.ValidationError` if the frame does not match the
    envelope shape, or :class:`json.JSONDecodeError` if it is not valid JSON.
    """
    data: Any = json.loads(raw)
    return Envelope.model_validate(data)


def _rgb(color: RGB) -> list[int]:
    """Normalize an RGB triplet to a JSON-friendly list of three ints."""
    r, g, b = color
    return [int(r), int(g), int(b)]


# --------------------------------------------------------------------------- #
# host -> device frame constructors
# --------------------------------------------------------------------------- #


def make_config(
    *,
    page_id: str,
    rows: int,
    cols: int,
    buttons: list[dict[str, Any]],
    background: RGB,
    default_outline_color: RGB,
    msg_id: str | None = None,
) -> Envelope:
    """Construct a ``config`` frame in the device config wire shape.

    The payload carries ``version``, ``default_page``, a ``theme`` block, a
    ``pages`` list (each page has a string ``id``, a ``grid`` of ``[rows, cols]``,
    and ``buttons``), and an ``icons_manifest``.

    :param page_id: id of the page (e.g. ``"main"``).
    :param rows: grid row count.
    :param cols: grid column count.
    :param buttons: list of button descriptors (``id``/``label``/``row``/``col``).
    :param background: page background color as an RGB triplet.
    :param default_outline_color: default button outline color as an RGB triplet.
    """
    return Envelope(
        type=MessageType.CONFIG,
        id=msg_id,
        payload={
            "version": 1,
            "default_page": page_id,
            "theme": {
                "background": _rgb(background),
                "default_outline_color": _rgb(default_outline_color),
            },
            "pages": [
                {
                    "id": page_id,
                    "grid": [rows, cols],
                    "buttons": buttons,
                },
            ],
            "icons_manifest": [],
        },
    )


def make_ping(*, msg_id: str | None = None) -> Envelope:
    """Construct a ``ping`` keepalive frame the device echoes as ``pong``."""
    return Envelope(type=MessageType.PING, id=msg_id, payload={})


def make_set_button_state(
    *, page: str, button: str, state: dict[str, Any], msg_id: str | None = None
) -> Envelope:
    """Construct a ``set_button_state`` frame.

    ``state`` carries any of ``label``, ``icon``, ``color``, ``enabled``,
    ``badge`` to merge into the target button's runtime state.
    """
    return Envelope(
        type=MessageType.SET_BUTTON_STATE,
        id=msg_id,
        payload={"page": page, "button": button, "state": state},
    )


def make_set_led(*, index: int, color: RGB, msg_id: str | None = None) -> Envelope:
    """Construct a ``set_led`` frame setting one LED to an RGB color."""
    return Envelope(
        type=MessageType.SET_LED,
        id=msg_id,
        payload={"index": int(index), "color": _rgb(color)},
    )


def make_set_page(*, page: str, msg_id: str | None = None) -> Envelope:
    """Construct a ``set_page`` frame switching the device to page ``page`` (5.3)."""
    return Envelope(
        type=MessageType.SET_PAGE,
        id=msg_id,
        payload={"page": page},
    )


def make_notify(
    *,
    text: str,
    duration_ms: int = 2000,
    color: RGB | None = None,
    msg_id: str | None = None,
) -> Envelope:
    """Construct a ``notify`` frame asking the device to show a transient toast (5.3)."""
    payload: dict[str, Any] = {"text": text, "duration_ms": duration_ms}
    if color is not None:
        payload["color"] = _rgb(color)
    return Envelope(
        type=MessageType.NOTIFY,
        id=msg_id,
        payload=payload,
    )


def make_icon_chunk(
    *,
    name: str,
    seq: int,
    total: int,
    data_b64: str,
    msg_id: str | None = None,
) -> Envelope:
    """Construct an ``icon_chunk`` frame streaming one base64 slice of an icon.

    Sent in response to a device ``request_icon``. ``total`` is the
    chunk count so the device knows when reassembly is complete.
    """
    return Envelope(
        type=MessageType.ICON_CHUNK,
        id=msg_id,
        payload={"name": name, "seq": seq, "total": total, "data_b64": data_b64},
    )
