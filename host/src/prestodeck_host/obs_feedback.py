"""Reflect live OBS state onto PrestoDeck buttons.

An ``obs`` action can carry a ``feedback`` key so its button mirrors OBS state --
a record button that glows red while recording, a mic button that turns green
when muted, a scene button highlighted while its scene is live. This module
subscribes to obs-websocket events, tracks the boolean state behind each
feedback key, and pushes ``set_button_state`` frames to the connected devices so
the buttons stay correct even when OBS is changed directly.

Supported feedback keys:

* ``record`` / ``stream`` / ``replay`` -- output active state,
* ``mute:<inputName>``               -- an audio input's mute state,
* ``scene:<sceneName>``              -- whether that scene is the program scene.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from prestodeck_host.log import get_logger
from prestodeck_host.obs import ObsClient, ObsError

_logger = get_logger(__name__)

# Map obs-websocket event types to the feedback key they update and the field
# in the event data that carries the boolean state. Mute/scene are special-cased.
_OUTPUT_EVENTS = {
    "RecordStateChanged": "record",
    "StreamStateChanged": "stream",
    "ReplayBufferStateChanged": "replay",
}


@dataclass(frozen=True)
class FeedbackBinding:
    """A button that mirrors an OBS feedback key, with its on/off appearance."""

    page: str
    button: str
    key: str
    on_label: str | None = None
    off_label: str | None = None
    on_color: tuple[int, int, int] | None = None
    off_color: tuple[int, int, int] | None = None
    on_icon: str | None = None
    off_icon: str | None = None


PushState = Callable[[str, str, dict[str, Any]], Awaitable[None]]
Bindings = Callable[[], list[FeedbackBinding]]


class ObsFeedback:
    """Bridges obs-websocket events to device ``set_button_state`` pushes."""

    def __init__(self, obs: ObsClient, bindings: Bindings, push: PushState) -> None:
        """Wire the feedback bridge.

        :param obs: the connected OBS client to subscribe to.
        :param bindings: callable returning the current feedback bindings (read
            fresh each time so config hot-reload is picked up).
        :param push: coroutine ``(page, button, state)`` broadcasting a
            ``set_button_state`` to the connected devices.
        """
        self._obs = obs
        self._bindings = bindings
        self._push = push
        self._state: dict[str, bool] = {}
        obs.on_connect(self.resync)
        for event_type in _OUTPUT_EVENTS:
            obs.on_event(event_type, self._make_output_handler(event_type))
        obs.on_event("InputMuteStateChanged", self._on_mute)
        obs.on_event("CurrentProgramSceneChanged", self._on_scene)

    def _make_output_handler(self, event_type: str) -> Callable[[dict[str, Any]], Awaitable[None]]:
        key = _OUTPUT_EVENTS[event_type]

        async def handler(data: dict[str, Any]) -> None:
            await self._set(key, bool(data.get("outputActive")))

        return handler

    async def _on_mute(self, data: dict[str, Any]) -> None:
        await self._set(f"mute:{data.get('inputName')}", bool(data.get("inputMuted")))

    async def _on_scene(self, data: dict[str, Any]) -> None:
        active = data.get("sceneName") or data.get("currentProgramSceneName")
        for binding in self._bindings():
            if binding.key.startswith("scene:"):
                await self._set(binding.key, binding.key == f"scene:{active}")

    async def _set(self, key: str, value: bool, force: bool = False) -> None:
        """Record a feedback key's new state and push it to matching buttons."""
        changed = self._state.get(key) != value
        self._state[key] = value
        if not changed and not force:
            return
        bound = [binding for binding in self._bindings() if binding.key == key]
        if bound:
            _logger.info("OBS state %s -> %s", key, "on" if value else "off")
        for binding in bound:
            await self._push_binding(binding, value)

    async def _push_binding(self, binding: FeedbackBinding, value: bool) -> None:
        state: dict[str, Any] = {}
        label = binding.on_label if value else binding.off_label
        color = binding.on_color if value else binding.off_color
        icon = binding.on_icon if value else binding.off_icon
        if label is not None:
            state["label"] = label
        if color is not None:
            state["color"] = list(color)
        if icon is not None:
            state["icon"] = icon
        if state:
            await self._push(binding.page, binding.button, state)

    async def resync(self) -> None:
        """Query OBS for the current state of every bound key and push it out.

        Called when OBS (re)connects and whenever a device connects or the deck
        reloads, so buttons show the correct state immediately.
        """
        if not self._obs.connected:
            return
        keys = {binding.key for binding in self._bindings()}
        for key, request in (
            ("record", "GetRecordStatus"),
            ("stream", "GetStreamStatus"),
            ("replay", "GetReplayBufferStatus"),
        ):
            if key in keys:
                await self._query(key, request, "outputActive", force=True)

        scene_keys = {k for k in keys if k.startswith("scene:")}
        if scene_keys:
            try:
                data = await self._obs.request("GetCurrentProgramScene")
            except ObsError:
                data = {}
            active = data.get("currentProgramSceneName") or data.get("sceneName")
            for key in scene_keys:
                await self._set(key, key == f"scene:{active}", force=True)

        for key in keys:
            if key.startswith("mute:"):
                name = key[len("mute:"):]
                await self._query(
                    key, "GetInputMute", "inputMuted", {"inputName": name}, force=True
                )

    async def _query(
        self,
        key: str,
        request: str,
        field: str,
        data: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        """Query one OBS status request and set the feedback key from ``field``."""
        try:
            response = await self._obs.request(request, data)
        except ObsError as exc:
            _logger.debug("OBS resync %s failed: %s", request, exc)
            return
        await self._set(key, bool(response.get(field)), force=force)


def bindings_from_config(pages: Any) -> list[FeedbackBinding]:
    """Extract feedback bindings from a deck config's pages.

    Scans every button for an ``obs`` action with a ``feedback`` key and records
    its position and on/off appearance.
    """
    from prestodeck_host.actions.obs import ObsAction

    bindings: list[FeedbackBinding] = []
    for page in pages:
        for button in page.buttons:
            action = button.action
            if isinstance(action, ObsAction) and action.feedback:
                bindings.append(
                    FeedbackBinding(
                        page=page.id,
                        button=button.id,
                        key=action.feedback,
                        on_label=action.on_label,
                        off_label=action.off_label,
                        on_color=action.on_color,
                        off_color=action.off_color,
                        on_icon=action.on_icon,
                        off_icon=action.off_icon,
                    )
                )
    return bindings
