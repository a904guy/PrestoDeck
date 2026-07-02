"""Per-device WebSocket session.

A :class:`Session` owns one connected device's lifecycle and message pump for
the duration of its WebSocket connection:

    ``hello`` received  ->  push the resolved ``config`` (from deck.yaml) plus an
    icon manifest  ->  stream icon bytes on ``request_icon``  ->  log presses

Sessions are namespaced by ``device_id`` so that full multi-device fan-out
can be layered on without restructuring. Any inbound frame is treated
as keepalive; any traffic resets the device's 30s idle timeout.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from prestodeck_host import protocol
from prestodeck_host.actions.base import ActionContext
from prestodeck_host.config import DeckConfig, resolve_for_device
from prestodeck_host.engine import ActionEngine
from prestodeck_host.icons import IconStore
from prestodeck_host.log import get_logger
from prestodeck_host.protocol import Envelope, MessageType
from prestodeck_host.state import StateStore

if TYPE_CHECKING:
    from prestodeck_host.obs import ObsClient

_logger = get_logger(__name__)

# A coroutine that writes a single frame to the transport.
SendFrame = Callable[[Envelope], Awaitable[None]]


class Session:
    """A single connected device's lifecycle and message pump.

    Constructed after the device's ``hello`` has been parsed so it can be
    namespaced by ``device_id`` from the outset.
    """

    def __init__(
        self,
        *,
        device_id: str,
        firmware: str,
        peer: str,
        send: SendFrame,
        config: DeckConfig,
        icon_store: IconStore,
        engine: ActionEngine,
        store: StateStore,
        obs: ObsClient | None = None,
    ) -> None:
        self._device_id = device_id
        self._firmware = firmware
        self._peer = peer
        self._send = send
        self._config = config
        self._icon_store = icon_store
        self._engine = engine
        self._store = store
        self._obs = obs
        self._current_page = config.default_page

    @property
    def device_id(self) -> str:
        """Stable identifier for the connected device."""
        return self._device_id

    @property
    def firmware(self) -> str:
        """Firmware/library version reported by the device in ``hello``."""
        return self._firmware

    @property
    def peer(self) -> str:
        """Human-readable remote address of the connected device."""
        return self._peer

    def set_config(self, config: DeckConfig) -> None:
        """Update the session's config reference (used on hot reload)."""
        self._config = config

    async def start(self) -> None:
        """Push the resolved deck config, then restore stateful button visuals."""
        await self.push_config()
        await self.restore_button_states()

    async def push_button_state(self, page: str, button: str, state: dict[str, Any]) -> None:
        """Send a ``set_button_state`` frame (used by OBS live-state feedback)."""
        await self._send(protocol.make_set_button_state(page=page, button=button, state=state))

    async def restore_button_states(self) -> None:
        """Re-apply persisted visual state to stateful buttons after (re)connect.

        A freshly (re)drawn device shows each button's base label/colour/icon.
        Toggle buttons persist their on/off state on the host, so replay it here
        so the device reflects reality immediately -- without waiting for the
        user to press the button. (OBS-feedback buttons are handled separately
        by :meth:`ObsFeedback.resync`, which re-queries live OBS state.)
        """
        from prestodeck_host.actions.toggle import ToggleAction

        for page in self._config.pages:
            for button in page.buttons:
                action = button.action
                if not isinstance(action, ToggleAction):
                    continue
                key = f"{self._device_id}:{action.id}"
                is_on = (
                    bool(self._store.get(key, action.initial))
                    if self._store is not None
                    else action.initial
                )
                state = action.visual_for(is_on)
                if state:
                    await self.push_button_state(page.id, button.id, state)

    async def push_config(self) -> None:
        """Resolve the current deck config + icon manifest and send it."""
        manifest = self._icon_store.manifest()
        payload = resolve_for_device(self._config, manifest)
        _logger.info(
            "[%s] pushing config: %d page(s), default=%s, %d icon(s)",
            self._device_id,
            len(self._config.pages),
            self._config.default_page,
            len(manifest),
        )
        await self._send(Envelope(type=MessageType.CONFIG, id=None, payload=payload))

    async def handle(self, message: Envelope) -> None:
        """Dispatch one inbound frame.

        Logs button presses/releases, streams icons on ``request_icon``, and
        treats every frame as keepalive.
        """
        if message.type is MessageType.BUTTON_PRESS:
            page = str(message.payload.get("page", ""))
            button = str(message.payload.get("button", ""))
            _logger.info("[%s] button_press page=%s button=%s", self._device_id, page, button)
            ctx = ActionContext(
                device_id=self._device_id,
                page=page,
                button=button,
                send=self._send,
                event=message.payload,
                store=self._store,
                obs=self._obs,
            )
            await self._engine.dispatch(page, button, ctx)
        elif message.type is MessageType.BUTTON_RELEASE:
            page = str(message.payload.get("page", ""))
            button = str(message.payload.get("button", ""))
            held_ms = message.payload.get("held_ms")
            _logger.info(
                "[%s] button_release page=%s button=%s held_ms=%s",
                self._device_id,
                page,
                button,
                held_ms,
            )
        elif message.type is MessageType.PAGE_CHANGED:
            changed_page = message.payload.get("page")
            if changed_page is not None:
                self._current_page = str(changed_page)
            _logger.info("[%s] page_changed -> %s", self._device_id, changed_page)
        elif message.type is MessageType.REQUEST_ICON:
            await self._stream_icon(str(message.payload.get("name", "")))
        elif message.type is MessageType.PONG:
            _logger.debug("[%s] pong", self._device_id)
        else:
            _logger.debug("[%s] inbound %s (keepalive)", self._device_id, message.type.value)

    async def _stream_icon(self, name: str) -> None:
        """Stream icon ``name`` to the device as a sequence of ``icon_chunk`` frames."""
        chunks = self._icon_store.chunks(name)
        if chunks is None:
            _logger.warning("[%s] cannot stream unknown icon %r", self._device_id, name)
            return
        _logger.info("[%s] streaming icon %r in %d chunk(s)", self._device_id, name, len(chunks))
        for chunk in chunks:
            await self._send(protocol.make_icon_chunk(**chunk))
